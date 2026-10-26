"""Exercise model tensor contracts and geometry without downloading weights in CI."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app.vision import CpuVision, contains, decode_text, person_boxes


def logits_for(tokens):
    logits = np.full((len(tokens), 1, 96), -20.0, dtype=np.float32)
    for i, token in enumerate(tokens):
        logits[i, 0, token] = 20
    return logits


def test_ctc_keeps_leading_zeroes_and_case_and_separates_repeated_digits():
    text, confidence = decode_text(logits_for([1, 1, 0, 1, 2, 3, 37]))
    assert text == "0012A"
    assert confidence > 0.99
    assert decode_text(logits_for([95])) == ("", 0.0)
    assert decode_text(logits_for([0])) == ("", 0.0)
    assert contains((0.0, 0.0, 1.0, 1.0), (0.2, 0.2, 0.3, 0.3))
    assert not contains((0.0, 0.0, 0.3, 0.3), (0.2, 0.2, 0.3, 0.3))


def detector_outputs():
    cls = np.zeros((1, 2704, 80), dtype=np.float32)
    cls[0, 52 * 20 + 20, 0] = 0.95
    cls[0, 52 * 20 + 21, 0] = 0.8  # same person, suppressed
    reg = np.zeros((1, 2704, 32), dtype=np.float32)
    return [reg, cls]  # output ordering is deliberately reversed


def test_person_detection_suppresses_duplicate_boxes_and_ignores_other_classes():
    boxes = person_boxes(detector_outputs())
    assert len(boxes) == 1
    assert all(0 <= v <= 1 for v in boxes[0])
    assert person_boxes([np.zeros((1, 2704, 80)), np.zeros((1, 2704, 32))]) == []


def test_cpu_engine_uses_the_expected_input_shapes_and_only_body_embeddings(
    monkeypatch,
):
    import onnxruntime as ort

    calls = []

    class Session:
        def __init__(self, path, **kwargs):
            self.key = Path(path).stem
            assert kwargs["providers"] == ["CPUExecutionProvider"]

        def get_inputs(self):
            return [SimpleNamespace(name="input")]

        def run(self, outputs, inputs):
            tensor = inputs["input"]
            calls.append((self.key, tensor.shape))
            if self.key == "text_detector":
                probability = np.zeros((736, 736), dtype=np.float32)
                probability[300:340, 200:300] = 0.9
                probability[0, 0] = 0.8  # noise is too small to be a word
                return [probability]
            if self.key == "text_reader":
                return [logits_for([1, 0, 2, 0, 3])]
            if self.key == "people_detector":
                return detector_outputs()
            return [np.ones((1, 768, 1, 1), dtype=np.float32)]

    monkeypatch.setattr(ort, "InferenceSession", Session)
    engine = CpuVision(
        {
            k: Path(k + ".onnx")
            for k in ("text_detector", "text_reader", "people_detector", "appearance")
        }
    )
    image = Image.new("RGB", (1200, 800), "white")
    (reading,) = engine.ocr(image)
    assert reading.value == "012"
    assert reading.region[2] > 0 and reading.region[3] > 0
    (rider,) = engine.riders(image)
    assert np.linalg.norm(rider.vector) == pytest.approx(1.0)
    assert calls == [
        ("text_detector", (1, 3, 736, 736)),
        ("text_reader", (1, 3, 32, 100)),
        ("people_detector", (1, 3, 416, 416)),
        ("appearance", (1, 3, 256, 128)),
    ]


def test_people_detection_preserves_aspect_and_maps_padding_back_to_the_photo(
    monkeypatch,
):
    from app import vision

    engine = CpuVision.__new__(CpuVision)
    inputs = []

    def infer(key, tensor):
        if key == "people_detector":
            inputs.append(tensor)
            return []
        return [np.ones((1, 768, 1, 1), dtype=np.float32)]

    engine._run = infer
    monkeypatch.setattr(vision, "person_boxes", lambda output: [(0.25, 0.25, 0.5, 0.5)])
    (rider,) = engine.riders(Image.new("RGB", (1200, 600), "red"))
    assert rider.region == pytest.approx((0.25, 0.0, 0.5, 1.0))
    # The top row is padding, not a vertically stretched red image.
    assert np.allclose(
        inputs[0][0, :, 0, 0],
        np.array([-103.53, -116.28, -123.675]) / [57.375, 57.12, 58.395],
    )


def test_small_bibs_in_large_photos_are_read_at_native_scale_and_mapped_back():
    engine = CpuVision.__new__(CpuVision)

    def infer(key, tensor):
        if key == "text_reader":
            return [logits_for([2, 0, 1])]
        # A tiny green bib is unreadable after shrinking the whole large frame,
        # but survives in an overlapping native-resolution tile.
        green = (tensor[0, 1] > 1) & (tensor[0, 0] < 0) & (tensor[0, 2] < 0)
        probability = np.zeros((736, 736), dtype=np.float32)
        if green.sum() >= 40:
            probability[green] = 0.99
        return [probability]

    engine._run = infer
    image = Image.new("RGB", (2400, 1800), "white")
    from PIL import ImageDraw

    ImageDraw.Draw(image).rectangle((1800, 1200, 1820, 1210), fill=(0, 255, 0))
    readings = engine.ocr(image)
    assert readings and {r.value for r in readings} == {"10"}
    for reading in readings:
        x, y, w, h = reading.region
        assert x <= 1810 / 2400 <= x + w
        assert y <= 1205 / 1800 <= y + h
