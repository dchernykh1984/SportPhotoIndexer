"""CPU inference with the pinned OpenCV Zoo models (see licenses/ and MODEL_NOTICES.md).

Pre/postprocessing uses Pillow and NumPy so Windows ARM64 needs no OpenCV wheel.
Coordinates refer to the EXIF-oriented image and are normalized x, y, width, height.
"""

from __future__ import annotations

import math
import re
import string
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

Region = tuple[float, float, float, float]
# Reads below this are noise; recognition accepts from its own, higher threshold.
MIN_OCR = 0.8


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


def decode_text(logits, *, alphabet=None, probabilities=False) -> tuple[str, float]:
    default_alphabet = (
        string.digits
        + string.ascii_lowercase
        + string.ascii_uppercase
        + string.punctuation
    )
    characters = ["blank", *(alphabet if alphabet is not None else default_alphabet)]
    rows = np.asarray(logits).reshape(-1, logits.shape[-1])
    rows = rows if probabilities else _softmax(rows)
    chars, scores = [], []
    previous = -1
    for row in rows:
        token = int(row.argmax())
        if token and token != previous:
            if token >= len(characters):
                return "", 0.0
            chars.append(characters[token])
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


def _person_windows(region, size):
    """Overlapping squares, 0.4 of a person's height, over them and beside them.

    A bib on a chest, arm, belt, handlebar or seat post is too small for the text
    detector in the whole frame or a native-resolution tile: it finds plate digits
    only once they are about a tenth of its input. The zone reaches past the body to
    a handlebar in front, a seat post behind and the bike below.
    """
    width, height = size
    x, y, w, h = region
    left, right = max(0, x - 0.3 * w) * width, min(1, x + 1.3 * w) * width
    top, bottom = max(0, y - 0.05 * h) * height, min(1, y + 1.2 * h) * height
    side = max(64, 0.4 * h * height)

    def starts(start, end):
        count = max(1, math.ceil((end - start - side) / (0.75 * side)) + 1)
        span = end - start - side
        return [
            start + span * (n / (count - 1) if count > 1 else 0.5) for n in range(count)
        ]

    for b in starts(top, bottom):
        for a in starts(left, right):
            a, b = max(0, a), max(0, b)
            yield (
                round(a),
                round(b),
                round(min(width, a + side)),
                round(min(height, b + side)),
            )


def _overlap(a, b):
    return (
        a[0] < b[0] + b[2]
        and b[0] < a[0] + a[2]
        and a[1] < b[1] + b[3]
        and b[1] < a[1] + a[3]
    )


def _combined(readings):
    """One reading per bib and spot: windows overlap, so a plate is often read twice.

    Independent reads that agree raise the confidence to 1 - prod(1 - c); a lone
    digit read once stays as uncertain as the reader said.
    """
    clusters: list[list[Reading]] = []
    for reading in sorted(readings, key=lambda r: r.confidence, reverse=True):
        for cluster in clusters:
            if cluster[0].value == reading.value and _overlap(
                cluster[0].region, reading.region
            ):
                cluster.append(reading)
                break
        else:
            clusters.append([reading])
    return [
        Reading(
            best.value,
            1 - math.prod(1 - r.confidence for r in [best, *rest]),
            best.region,
        )
        for best, *rest in clusters
    ]


def _whole_bibs(readings):
    """Drop a fragment read on the same plate as a longer bib: "6" over "16"."""
    return [
        r
        for r in readings
        if not any(
            len(o.value) > len(r.value)
            and r.value in o.value
            and _overlap(r.region, o.region)
            for o in readings
        )
    ]


def _map_reading(reading, box, image):
    x, y, w, h = reading.region
    left, top, right, bottom = box
    # Discard partial words cut by an internal tile boundary.
    if (left > 0 and x < 0.01) or (top > 0 and y < 0.01):
        return None
    if (right < image.width and x + w > 0.99) or (
        bottom < image.height and y + h > 0.99
    ):
        return None
    width, height = right - left, bottom - top
    region = (
        (left + x * width) / image.width,
        (top + y * height) / image.height,
        w * width / image.width,
        h * height / image.height,
    )
    return Reading(reading.value, reading.confidence, region)


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
    def __init__(self, models: dict[str, Path], *, threads: int = 1) -> None:
        import onnxruntime as ort

        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        self.sessions = {
            key: ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            for key, path in models.items()
        }
        metadata = self.sessions["text_reader"].get_modelmeta().custom_metadata_map
        self.characters = [*metadata["character"].splitlines(), " "]

    def _run(self, key, blob):
        session = self.sessions[key]
        return session.run(None, {session.get_inputs()[0].name: blob})

    def ocr(self, image: Image.Image) -> list[Reading]:
        boxes = [(0, 0, image.width, image.height)]
        for person in self._people(image):
            boxes.extend(_person_windows(person, image.size))
        found = []
        for box in boxes:
            with image.crop(box) as tile:
                for reading in self._read_crop(tile):
                    if mapped := _map_reading(reading, box, image):
                        found.append(mapped)
        return _combined(_whole_bibs(found))

    def _read_crop(self, image: Image.Image) -> list[Reading]:
        square, padding = _letterbox(image, 736)
        # The OpenCV Zoo export takes (BGR - mean) / 255; dividing by Paddle's std
        # saturates it, so it sees either no text or text everywhere.
        blob = _blob(
            square,
            (736, 736),
            (122.67891434, 116.66876762, 104.00698793),
            (255.0,) * 3,
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
            region = _unpad(
                (box[0], box[1], box[2] - box[0], box[3] - box[1]), padding, 736
            )
            if region is None:
                continue
            crop = _crop(image, region)
            if min(crop.size) < 2:
                continue  # a box under a pixel once mapped back to a small window
            text, confidence = self._read_text(crop)
            text = text.strip()
            if (
                re.fullmatch(r"[A-Za-z0-9-]{1,32}", text)
                and any(c.isdigit() for c in text)
                and confidence >= MIN_OCR
            ):
                readings.append(Reading(text, confidence, region))
        return readings

    def _read_text(self, image):
        # Paddle's mobile reader preserves aspect, with gray padding to width 320.
        width = min(320, max(1, math.ceil(48 * image.width / image.height)))
        data = _blob(image, (width, 48), (127.5,) * 3, (127.5,) * 3, bgr=True)
        tensor = np.zeros((1, 3, 48, 320), dtype=np.float32)
        tensor[:, :, :, :width] = data
        return decode_text(
            self._run("text_reader", tensor)[0],
            alphabet=self.characters,
            probabilities=True,
        )

    def _people(self, image: Image.Image) -> list[Region]:
        square, padding = _letterbox(image, 416)
        blob = _blob(
            square,
            (416, 416),
            (103.53, 116.28, 123.675),
            (57.375, 57.12, 58.395),
            bgr=True,
        )
        regions = (
            _unpad(padded, padding, 416)
            for padded in person_boxes(self._run("people_detector", blob))
        )
        return [region for region in regions if region is not None]

    def riders(self, image: Image.Image) -> list[Rider]:
        found = []
        for region in self._people(image):
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
