"""CPU inference with the pinned OpenCV Zoo models (see licenses/ and MODEL_NOTICES.md).

Pre/postprocessing uses Pillow and NumPy so Windows ARM64 needs no OpenCV wheel.
Coordinates refer to the EXIF-oriented image and are normalized x, y, width, height.
"""

from __future__ import annotations

import math
import os
import re
import string
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

Region = tuple[float, float, float, float]


@dataclass(frozen=True)
class Reading:
    value: str
    confidence: float
    region: Region


@dataclass(frozen=True)
class Rider:
    region: Region
    vector: np.ndarray


def contains(outer: Region, inner: Region) -> bool:
    x, y, w, h = outer
    a, b, c, d = inner
    return x <= a and y <= b and a + c <= x + w and b + d <= y + h


def _softmax(array, axis=-1):
    exp = np.exp(array - np.max(array, axis=axis, keepdims=True))
    return exp / exp.sum(axis=axis, keepdims=True)


def _blob(image, size, mean, std, *, bgr=False):
    values = np.asarray(image.resize(size), dtype=np.float32)
    if bgr:
        values = values[:, :, ::-1]
    values = (values - np.array(mean, dtype=np.float32)) / np.array(
        std, dtype=np.float32
    )
    return values.transpose(2, 0, 1)[None].astype(np.float32)


def _components(probability):
    """Join adjacent text pixels, then bound components; cap noisy maps before OCR."""
    binary = Image.fromarray((probability > 0.3).astype(np.uint8) * 255)
    todo = np.asarray(binary.filter(ImageFilter.MaxFilter(3))).copy() > 0
    height, width = todo.shape
    boxes = []
    for y, x in np.argwhere(todo):
        if not todo[y, x]:
            continue
        todo[y, x] = False
        stack = [(int(x), int(y))]
        left = right = int(x)
        top = bottom = int(y)
        while stack:
            a, b = stack.pop()
            left, right = min(left, a), max(right, a)
            top, bottom = min(top, b), max(bottom, b)
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                c, d = a + dx, b + dy
                if 0 <= c < width and 0 <= d < height and todo[d, c]:
                    todo[d, c] = False
                    stack.append((c, d))
        if right - left >= 3 and bottom - top >= 3:
            score = float(probability[top : bottom + 1, left : right + 1].max())
            if score >= 0.5:
                boxes.append((score, left, top, right + 1, bottom + 1))
    return sorted(boxes, reverse=True)[:200]


def decode_text(logits) -> tuple[str, float]:
    # Model order: digits, lower/upper Latin, ASCII punctuation; blank is zero.
    alphabet = (
        string.digits
        + string.ascii_lowercase
        + string.ascii_uppercase
        + string.punctuation
    )
    probabilities = _softmax(np.asarray(logits).reshape(-1, logits.shape[-1]))
    chars, scores = [], []
    previous = -1
    for row in probabilities:
        token = int(row.argmax())
        if token and token != previous:
            if token > len(alphabet):
                return "", 0.0
            chars.append(alphabet[token - 1])
            scores.append(float(row[token]))
        previous = token
    return "".join(chars), min(scores, default=0.0)


def _region(box, side):
    x, y, right, bottom = np.clip(box, 0, side) / side
    return (float(x), float(y), float(right - x), float(bottom - y))


def _crop(image, region):
    x, y, w, h = region
    return image.crop(
        (
            x * image.width,
            y * image.height,
            (x + w) * image.width,
            (y + h) * image.height,
        )
    )


def _letterbox(image, side):
    scale = min(side / image.width, side / image.height)
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    left, top = (side - width) // 2, (side - height) // 2
    square = Image.new("RGB", (side, side))
    square.paste(image.resize((width, height)), (left, top))
    return square, (left, top, width, height)


def _unpad(region, padding, side):
    left, top, width, height = padding
    x, y, w, h = region
    bounds = np.clip(
        (
            (x * side - left) / width,
            (y * side - top) / height,
            ((x + w) * side - left) / width,
            ((y + h) * side - top) / height,
        ),
        0,
        1,
    )
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        return None
    return (
        float(bounds[0]),
        float(bounds[1]),
        float(bounds[2] - bounds[0]),
        float(bounds[3] - bounds[1]),
    )


def _iou(a, b):
    x = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    y = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    intersection = x * y
    return intersection / max(
        1e-9,
        (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection,
    )


def person_boxes(outputs):
    """Decode NanoDet's three pyramid levels; outputs may be returned in any order."""
    scores = sorted((v[0] for v in outputs if v.shape[-1] == 80), key=len, reverse=True)
    distances = sorted(
        (v[0] for v in outputs if v.shape[-1] == 32), key=len, reverse=True
    )
    proposals = []
    for cls, reg in zip(scores, distances, strict=True):
        side = math.isqrt(len(cls))
        stride = 416 / side
        yy, xx = np.mgrid[:side, :side]
        anchors = np.column_stack((xx.ravel(), yy.ravel())) * stride + 0.5 * (
            stride - 1
        )
        dist = (_softmax(reg.reshape(-1, 4, 8)) @ np.arange(8)) * stride
        boxes = np.column_stack((anchors - dist[:, :2], anchors + dist[:, 2:]))
        # COCO class zero is person. ReID deliberately uses the whole rider's body.
        for i in np.flatnonzero(cls[:, 0] >= 0.4):
            proposals.append((float(cls[i, 0]), boxes[i]))
    kept = []
    for _, box in sorted(proposals, key=lambda p: p[0], reverse=True):
        if all(_iou(box, other) <= 0.5 for other in kept):
            kept.append(box)
        if len(kept) == 30:
            break
    return [_region(box, 416) for box in kept if box[2] > box[0] and box[3] > box[1]]


class CpuVision:
    def __init__(self, models: dict[str, Path]) -> None:
        import onnxruntime as ort

        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = min(4, os.cpu_count() or 1)
        self.sessions = {
            key: ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            for key, path in models.items()
        }

    def _run(self, key, blob):
        session = self.sessions[key]
        return session.run(None, {session.get_inputs()[0].name: blob})

    def ocr(self, image: Image.Image) -> list[Reading]:
        blob = _blob(
            image,
            (736, 736),
            (123.675, 116.28, 103.53),
            (58.395, 57.12, 57.375),
            bgr=True,
        )
        probability = np.asarray(self._run("text_detector", blob)[0]).squeeze()
        height, width = probability.shape
        readings = []
        for _, left, top, right, bottom in _components(probability):
            # DB-style expansion leaves a margin around the thresholded text.
            margin = (bottom - top) * 0.35
            box = (
                max(0, left - margin) / width,
                max(0, top - margin) / height,
                min(width, right + margin) / width,
                min(height, bottom + margin) / height,
            )
            region = (box[0], box[1], box[2] - box[0], box[3] - box[1])
            crop = _crop(image, region)
            text_blob = _blob(crop, (100, 32), (127.5,) * 3, (127.5,) * 3, bgr=True)
            text, confidence = decode_text(self._run("text_reader", text_blob)[0])
            if (
                re.fullmatch(r"[A-Za-z0-9-]{1,32}", text)
                and any(c.isdigit() for c in text)
                and confidence >= 0.6
            ):
                readings.append(Reading(text, confidence, region))
        return readings

    def riders(self, image: Image.Image) -> list[Rider]:
        square, padding = _letterbox(image, 416)
        blob = _blob(
            square,
            (416, 416),
            (103.53, 116.28, 123.675),
            (57.375, 57.12, 58.395),
            bgr=True,
        )
        found = []
        for padded_region in person_boxes(self._run("people_detector", blob)):
            region = _unpad(padded_region, padding, 416)
            if region is None:
                continue
            crop = _crop(image, region)
            features = self._run(
                "appearance",
                _blob(
                    crop, (128, 256), (123.675, 116.28, 103.53), (58.395, 57.12, 57.375)
                ),
            )[0].ravel()
            norm = float(np.linalg.norm(features))
            if norm and np.isfinite(features).all():
                found.append(Rider(region, features / norm))
        return found
