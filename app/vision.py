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

from app import faces
from app.florence import Florence

Region = tuple[float, float, float, float]
# Reads below this are noise; recognition accepts from ACCEPT_OCR.
MIN_OCR = 0.8
ACCEPT_OCR = 0.95
# A lone digit is in every logo and word fragment; on test races it was wrong most
# often, so it needs a sure read or two windows that agree.
ACCEPT_LONE_DIGIT = 0.99
# Florence-2's lowest token probability on the small reader's scale: on the labelled
# races its 0.2 kept as much as the small reader's MIN_OCR, its 0.5 was as right as
# ACCEPT_OCR and a lone digit at 0.9 as right as ACCEPT_LONE_DIGIT.
FLORENCE_SCALE = ([0.2, 0.5, 0.9, 1.0], [MIN_OCR, ACCEPT_OCR, ACCEPT_LONE_DIGIT, 1.0])
# Person windows as a share of the person's height: the text detector finds digits once
# they fill about a tenth of a window. The finer windows catch digits smaller than that
# (a rider near the camera, a small plate) and run only with Florence-2, which vets the
# small reader's unsure reads; without it they added more wrong values than bibs.
WINDOWS = 0.4
FINER_WINDOWS = 0.25


@dataclass(frozen=True)
class Reading:
    value: str
    confidence: float
    region: Region


@dataclass(frozen=True)
class Rider:
    region: Region
    vector: np.ndarray
    # A clear, frontal enough face, only when the face models are loaded.
    face: np.ndarray | None = None


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


def _zone(region):
    """Where a person's bib can be: past the body to a handlebar in front, a seat
    post behind and the bike below. Left, top, right, bottom as image fractions."""
    x, y, w, h = region
    return (
        max(0, x - 0.3 * w),
        max(0, y - 0.05 * h),
        min(1, x + 1.3 * w),
        min(1, y + 1.2 * h),
    )


def _person_windows(region, size, share=WINDOWS):
    """Overlapping squares, ``share`` of a person's height, over a person's zone.

    A bib on a chest, arm, belt, handlebar or seat post is too small for the text
    detector in the whole frame or a native-resolution tile: it finds plate digits
    only once they are about a tenth of its input.
    """
    width, height = size
    left, top, right, bottom = _zone(region)
    left, right = left * width, right * width
    top, bottom = top * height, bottom * height
    side = max(64, share * region[3] * height)

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


def _clusters(readings):
    """Readings grouped by bib and spot, the most confident first in each group."""
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
    return clusters


def _combined(readings):
    """One reading per bib and spot: windows overlap, so a plate is often read twice.

    Independent reads that agree raise the confidence to 1 - prod(1 - c); a lone
    digit read once stays as uncertain as the reader said.
    """
    return [
        Reading(
            best.value,
            1 - math.prod(1 - r.confidence for r in [best, *rest]),
            best.region,
        )
        for best, *rest in _clusters(readings)
    ]


def _related(a, b):
    """Two different reads of one plate, one part of the other: "6" and "16"."""
    return (
        a.value != b.value
        and (a.value in b.value or b.value in a.value)
        and _overlap(a.region, b.region)
    )


def _bib_like(text):
    return bool(re.fullmatch(r"[A-Za-z0-9-]{1,32}", text)) and any(
        c.isdigit() for c in text
    )


def _sure(reading):
    needed = ACCEPT_LONE_DIGIT if len(reading.value) == 1 else ACCEPT_OCR
    return reading.confidence >= needed


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


def _read_florence(florence: Florence, image: Image.Image, people) -> list[Reading]:
    """The whole frame and each person's zone, stretched to the model's input.

    A crop a pixel wider can change what greedy decoding reads, so the edges are
    truncated exactly as on the benchmark (docs/recognition-benchmark.md).
    """
    found = []
    for left, top, right, bottom in [(0, 0, 1, 1), *map(_zone, people)]:
        box = (
            int(left * image.width),
            int(top * image.height),
            int(right * image.width),
            int(bottom * image.height),
        )
        if min(box[2] - box[0], box[3] - box[1]) < 16:
            continue
        with image.crop(box) as crop:
            texts = florence.read(crop)
        for text, probability, x, y, w, h in texts:
            if probability >= FLORENCE_SCALE[0][0] and _bib_like(text):
                width, height = right - left, bottom - top
                region = (left + x * width, top + y * height, w * width, h * height)
                found.append(Reading(text, probability, region))
    return [
        Reading(r.value, float(np.interp(r.confidence, *FLORENCE_SCALE)), r.region)
        for r in _combined(_whole_bibs(found))
    ]


class CpuVision:
    florence: Florence | None = None
    reads_faces = False

    def __init__(self, models: dict[str, Path], *, threads: int = 1) -> None:
        import onnxruntime as ort

        ort.disable_telemetry_events()
        options = ort.SessionOptions()
        options.log_severity_level = 3
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        # A larger set's Florence-2 parts are keyed "florence-2-base/vision_encoder".
        self.sessions = {
            key.rpartition("/")[2]: ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            for key, path in models.items()
            if Path(path).suffix == ".onnx"
        }
        metadata = self.sessions["text_reader"].get_modelmeta().custom_metadata_map
        self.characters = [*metadata["character"].splitlines(), " "]
        self.reads_faces = "face_detector" in self.sessions
        vocabulary = [Path(p) for p in models.values() if Path(p).suffix == ".json"]
        if vocabulary:
            self.florence = Florence(self.sessions, vocabulary[0])

    def _run(self, key, blob):
        session = self.sessions[key]
        return session.run(None, {session.get_inputs()[0].name: blob})

    def ocr(self, image: Image.Image) -> list[Reading]:
        people = self._people(image)
        boxes = [(0, 0, image.width, image.height)]
        for person in people:
            boxes.extend(_person_windows(person, image.size))
        small = _combined(_whole_bibs(self._read_windows(image, boxes)))
        if self.florence is None:
            return small
        read = _read_florence(self.florence, image, people)
        # The finer windows see the same pixels many times over: one vote per spot,
        # and only for bibs that neither cut nor extend a read already made, so they
        # add bibs without taking any away.
        finer = [
            b for p in people for b in _person_windows(p, image.size, FINER_WINDOWS)
        ]
        settled = [*small, *read]
        extra = [
            best
            for best, *_ in _clusters(self._read_windows(image, finer))
            if not any(_related(best, other) for other in settled)
        ]
        small = _combined([*small, *extra])
        # Florence-2 misreads far less: an unsure small read stays only when it agrees.
        seen = {r.value for r in read}
        kept = [r for r in small if _sure(r) or r.value in seen]
        return _combined(_whole_bibs([*kept, *read]))

    def _read_windows(self, image: Image.Image, boxes) -> list[Reading]:
        found = []
        for box in boxes:
            with image.crop(box) as tile:
                for reading in self._read_crop(tile):
                    if mapped := _map_reading(reading, box, image):
                        found.append(mapped)
        return found

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
            if _bib_like(text) and confidence >= MIN_OCR:
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
                face = self._face(image, region) if self.reads_faces else None
                found.append(Rider(region, features / norm, face))
        return found

    def _face(self, image: Image.Image, region: Region) -> np.ndarray | None:
        with image.crop(faces.head_box(region, image.size)) as head:
            if min(head.size) < 8:
                return None
            square, (left, top, width, _) = _letterbox(head, 640)
            bgr = np.asarray(square, dtype=np.float32)[:, :, ::-1].transpose(2, 0, 1)
            session = self.sessions["face_detector"]
            names = [o.name for o in session.get_outputs()]
            outputs = self._run("face_detector", np.ascontiguousarray(bgr[None]))
            face = faces.best_face(
                dict(zip(names, outputs, strict=True)), (left, top), width / head.width
            )
            # Small or doubtful faces matched strangers on the labelled races.
            if face is None or face[0] < 0.8 or face[1] < 24:
                return None
            rgb = np.asarray(faces.aligned(head, face[2]), dtype=np.float32)
        tensor = np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])
        vector = self._run("face_vectors", tensor)[0].ravel()
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm and np.isfinite(vector).all() else None
