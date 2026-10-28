"""Exercise model tensor contracts and geometry without downloading weights in CI."""

import string
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app.vision import (
    CpuVision,
    Reading,
    _combined,
    _overlap,
    _person_windows,
    _whole_bibs,
    contains,
    decode_text,
    person_boxes,
)


def logits_for(tokens):
    logits = np.full((len(tokens), 1, 96), -20.0, dtype=np.float32)
    for i, token in enumerate(tokens):
        logits[i, 0, token] = 20
    return logits


def _probabilities(logits):
    values = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return values / values.sum(axis=-1, keepdims=True)


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

        def get_modelmeta(self):
            alphabet = (
                string.digits
                + string.ascii_lowercase
                + string.ascii_uppercase
                + string.punctuation
            )
            return SimpleNamespace(
                custom_metadata_map={"character": "\n".join(alphabet)}
            )

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
                return [_probabilities(logits_for([1, 0, 2, 0, 3]))]
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
    readings = engine.ocr(image)
    assert readings and {r.value for r in readings} == {"012"}
    assert all(r.region[2] > 0 and r.region[3] > 0 for r in readings)
    # Bibs are read in the whole frame, then around the person found first.
    assert calls[:3] == [
        ("people_detector", (1, 3, 416, 416)),
        ("text_detector", (1, 3, 736, 736)),
        ("text_reader", (1, 3, 48, 320)),
    ]
    assert {c for c in calls} == {
        ("people_detector", (1, 3, 416, 416)),
        ("text_detector", (1, 3, 736, 736)),
        ("text_reader", (1, 3, 48, 320)),
    }
    calls.clear()
    (rider,) = engine.riders(image)
    assert np.linalg.norm(rider.vector) == pytest.approx(1.0)
    assert calls == [
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


def test_a_small_bib_beside_a_person_is_read_enlarged_and_mapped_back(monkeypatch):
    from PIL import ImageDraw

    from app import vision

    engine = CpuVision.__new__(CpuVision)
    engine.characters = [
        *string.digits,
        *string.ascii_lowercase,
        *string.ascii_uppercase,
        *string.punctuation,
        " ",
    ]
    detector_inputs = []

    def infer(key, tensor):
        if key == "people_detector":
            return []
        if key == "text_reader":
            return [_probabilities(logits_for([2, 0, 1]))]
        detector_inputs.append(tensor)
        # A tiny green plate: too few pixels in the whole frame, enough once enlarged.
        green = (tensor[0, 1] > 0.5) & (tensor[0, 0] < 0) & (tensor[0, 2] < 0)
        probability = np.zeros((736, 736), dtype=np.float32)
        if green.sum() >= 40:
            probability[green] = 0.99
        return [probability]

    engine._run = infer
    # A rider in the middle; the plate sits behind them, past the body's box.
    monkeypatch.setattr(vision, "person_boxes", lambda output: [(0.4, 0.3, 0.1, 0.5)])
    image = Image.new("RGB", (2400, 1800), "white")
    ImageDraw.Draw(image).rectangle((1265, 1200, 1285, 1210), fill=(0, 255, 0))
    readings = engine.ocr(image)
    assert readings and {r.value for r in readings} == {"10"}
    for reading in readings:
        x, y, w, h = reading.region
        assert x <= 1275 / 2400 <= x + w
        assert y <= 1205 / 1800 <= y + h
    # The OpenCV Zoo detector takes (BGR - mean) / 255: black padding stays small.
    assert np.allclose(
        detector_inputs[0][0, :, 0, 0],
        -np.array([122.67891434, 116.66876762, 104.00698793]) / 255,
    )


def test_with_florence_finer_windows_read_a_plate_too_small_for_the_body_windows(
    monkeypatch,
):
    from PIL import ImageDraw

    from app import vision

    engine = CpuVision.__new__(CpuVision)
    engine.characters = [*string.digits, *string.ascii_letters, " "]

    def infer(key, tensor):
        if key == "people_detector":
            return []
        if key == "text_reader":
            return [_probabilities(logits_for([2, 0, 1]))]
        # Seen only once the plate fills more of the detector's input than a window of
        # 0.4 of this rider's height gives it; a window of 0.25 does.
        green = (tensor[0, 1] > 0.5) & (tensor[0, 0] < 0) & (tensor[0, 2] < 0)
        probability = np.zeros((736, 736), dtype=np.float32)
        if green.sum() >= 1500:
            probability[green] = 0.99
        return [probability]

    engine._run = infer
    monkeypatch.setattr(vision, "person_boxes", lambda output: [(0.4, 0.3, 0.1, 0.5)])
    image = Image.new("RGB", (2400, 1800), "white")
    ImageDraw.Draw(image).rectangle((1100, 1200, 1111, 1231), fill=(0, 255, 0))
    assert engine.ocr(image) == []  # the small models alone keep to the 0.4 windows
    engine.florence = FakeFlorence({})
    assert {r.value for r in engine.ocr(image)} == {"10"}


def test_person_windows_cover_the_body_and_the_bike_beside_it_at_a_fixed_scale():
    finer = list(_person_windows((0.4, 0.2, 0.1, 0.5), (2000, 1000), 0.25))
    assert {(r - x, b - y) for x, y, r, b in finer} == {(125, 125)}
    windows = list(_person_windows((0.4, 0.2, 0.1, 0.5), (2000, 1000)))
    sides = {(r - x, b - y) for x, y, r, b in windows}
    assert sides == {(200, 200)}  # 0.4 of a 500-pixel person, square
    left = min(x for x, *_ in windows)
    right = max(r for _, _, r, _ in windows)
    bottom = max(b for *_, b in windows)
    assert left <= 740 and right >= 1060 and bottom >= 800
    assert all(0 <= x < r <= 2000 and 0 <= y < b <= 1000 for x, y, r, b in windows)


def test_a_fragment_of_a_longer_bib_on_the_same_plate_is_dropped():
    plate = Reading("16", 0.99, (0.5, 0.5, 0.1, 0.05))
    fragment = Reading("6", 0.99, (0.55, 0.5, 0.05, 0.05))
    elsewhere = Reading("1", 0.99, (0.1, 0.1, 0.05, 0.05))
    assert _whole_bibs([plate, fragment, elsewhere]) == [plate, elsewhere]


def test_paddle_reader_uses_crop_aspect_and_the_embedded_case_sensitive_dictionary():
    engine = CpuVision.__new__(CpuVision)
    engine.characters = ["0", "A", "a", " "]
    captured = []

    def infer(key, tensor):
        captured.append(tensor)
        return [
            np.array(
                [
                    [
                        [0.0, 0.0, 1.0, 0.0, 0.0],
                        [1.0, 0.0, 0.0, 0.0, 0.0],
                        [0.0, 0.0, 0.0, 1.0, 0.0],
                    ]
                ]
            )
        ]

    engine._run = infer
    text, confidence = engine._read_text(Image.new("RGB", (40, 80), "white"))
    assert text == "Aa" and confidence == 1
    (tensor,) = captured
    assert tensor.shape == (1, 3, 48, 320)
    assert np.all(tensor[:, :, :, :24] == 1)
    assert np.all(tensor[:, :, :, 24:] == 0)


def test_agreeing_reads_of_one_plate_combine_and_other_spots_stay_apart():
    a = Reading("7", 0.9, (0.5, 0.5, 0.1, 0.05))
    b = Reading("7", 0.9, (0.52, 0.5, 0.1, 0.05))
    far = Reading("7", 0.8, (0.1, 0.1, 0.05, 0.05))
    other = Reading("17", 0.9, (0.5, 0.5, 0.1, 0.05))
    combined = {
        (r.value, round(r.confidence, 4)) for r in _combined([a, b, far, other])
    }
    assert combined == {("7", 0.99), ("7", 0.8), ("17", 0.9)}


class FakeFlorence:
    def __init__(self, texts):
        self.texts = texts
        self.sizes = []

    def read(self, image):
        self.sizes.append(image.size)
        return self.texts.get(image.size, [])


def test_florence_reads_the_frame_and_each_zone_and_vets_the_small_readers_guesses():
    engine = CpuVision.__new__(CpuVision)
    person = (0.4, 0.25, 0.1, 0.5)  # zone: x 0.37-0.53, y 0.225-0.85 of 1000x800
    engine._people = lambda image: [person]
    small = [
        Reading("12", 0.9, (0.45, 0.5, 0.02, 0.02)),  # unsure, Florence agrees
        Reading("44", 0.9, (0.1, 0.1, 0.05, 0.05)),  # unsure, Florence saw nothing
        Reading("7", 0.995, (0.8, 0.8, 0.05, 0.05)),  # sure on its own
    ]
    engine._read_crop = lambda tile: small if tile.size == (1000, 800) else []
    image = Image.new("RGB", (1000, 800), "white")
    assert {r.value for r in engine.ocr(image)} == {"12", "44", "7"}

    engine.florence = FakeFlorence(
        {
            (1000, 800): [
                ("12", 0.6, 0.45, 0.5, 0.02, 0.02),
                ("GIANT", 0.9, 0.1, 0.1, 0.3, 0.1),  # banner text is no bib
                ("5", 0.1, 0.6, 0.6, 0.02, 0.02),  # too unsure to keep
            ],
            (160, 500): [("33", 0.5, 0.5, 0.5, 0.2, 0.1)],
        }
    )
    found = {r.value: r for r in engine.ocr(image)}
    assert engine.florence.sizes == [(1000, 800), (160, 500)]
    assert set(found) == {"12", "7", "33"}
    # Raw 0.6 is 0.96 on the small reader's scale; agreeing reads combine.
    assert found["12"].confidence == pytest.approx(1 - 0.1 * 0.04)
    assert found["33"].confidence == pytest.approx(0.95)
    assert found["33"].region == pytest.approx((0.45, 0.5375, 0.032, 0.0625))


def test_finer_windows_give_one_vote_per_spot_and_never_displace_a_read():
    engine = CpuVision.__new__(CpuVision)
    person = (0.4, 0.25, 0.1, 0.5)  # finer windows of 100 px: x 370-470 and 430-530
    engine._people = lambda image: [person]
    whole = [Reading("16", 0.97, (0.45, 0.5375, 0.01, 0.0125))]

    def read(tile):
        if tile.size == (1000, 800):
            return whole
        if tile.size == (100, 100):
            return [
                # The same spot in two overlapping windows: one view, not two.
                Reading("44", 0.9, (0.2, 0.2, 0.1, 0.2)),
                Reading("44", 0.9, (0.8, 0.2, 0.1, 0.2)),
                # Longer than the 16 read before, on the same plate.
                Reading("160", 0.99, (0.8, 0.5, 0.1, 0.2)),
            ]
        return []

    engine._read_crop = read
    engine.florence = FakeFlorence({})
    found = engine.ocr(Image.new("RGB", (1000, 800), "white"))
    assert "16" in {r.value for r in found} and "44" not in {r.value for r in found}
    # Elsewhere a 160 is a new bib; on the plate read as 16 it would replace it.
    assert not any(
        r.value == "160" and _overlap(r.region, whole[0].region) for r in found
    )


def test_finer_windows_skip_digits_too_small_for_a_bib_on_the_rider():
    engine = CpuVision.__new__(CpuVision)
    person = (0.4, 0.25, 0.1, 0.5)  # 400 px tall: a bib's digits from 10 px
    engine._people = lambda image: [person]

    def read(tile):
        if tile.size == (100, 100):
            return [
                Reading("3", 0.999, (0.2, 0.6, 0.05, 0.05)),  # 5 px: a sticker
                Reading("4", 0.999, (0.6, 0.6, 0.2, 0.2)),  # 20 px: a plate
            ]
        return []

    engine._read_crop = read
    engine.florence = FakeFlorence({})
    found = engine.ocr(Image.new("RGB", (1000, 800), "white"))
    assert {r.value for r in found} == {"4"}


def test_finer_windows_drop_a_fragment_of_a_bib_they_read_whole():
    engine = CpuVision.__new__(CpuVision)
    engine._people = lambda image: [(0.4, 0.25, 0.1, 0.5)]
    engine._read_crop = lambda tile: (
        [
            Reading("16", 0.9, (0.3, 0.3, 0.4, 0.2)),  # unsure, Florence-2 silent
            Reading("6", 0.995, (0.5, 0.3, 0.2, 0.2)),  # sure, but part of the 16
        ]
        if tile.size == (100, 100)
        else []
    )
    engine.florence = FakeFlorence({})
    found = engine.ocr(Image.new("RGB", (1000, 800), "white"))
    assert "6" not in {r.value for r in found}


def test_finer_windows_read_a_bib_where_only_a_discarded_guess_was():
    engine = CpuVision.__new__(CpuVision)
    engine._people = lambda image: [(0.4, 0.25, 0.1, 0.5)]
    guess = Reading("1", 0.85, (0.45, 0.5375, 0.01, 0.0125))  # unsure lone digit

    def read(tile):
        if tile.size == (1000, 800):
            return [guess]
        if tile.size == (100, 100):
            return [Reading("16", 0.97, (0.8, 0.5, 0.1, 0.2))]
        return []

    engine._read_crop = read
    engine.florence = FakeFlorence({})
    found = engine.ocr(Image.new("RGB", (1000, 800), "white"))
    assert "1" not in {r.value for r in found}
    assert any(r.value == "16" and _overlap(r.region, guess.region) for r in found)
