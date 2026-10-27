"""Face decoding, alignment and the quality gate, with fake model outputs."""

import math
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app import faces
from app.vision import CpuVision

STRIDES = (8, 16, 32)


def yunet(score=0.9, stride=16, row=10, col=20, height=32):
    outputs = {}
    for s in STRIDES:
        anchors = (640 // s) ** 2
        outputs[f"cls_{s}"] = np.zeros((1, anchors, 1), np.float32)
        outputs[f"obj_{s}"] = np.zeros((1, anchors, 1), np.float32)
        outputs[f"bbox_{s}"] = np.zeros((1, anchors, 4), np.float32)
        outputs[f"kps_{s}"] = np.zeros((1, anchors, 10), np.float32)
    i = row * (640 // stride) + col
    outputs[f"cls_{stride}"][0, i, 0] = outputs[f"obj_{stride}"][0, i, 0] = score
    outputs[f"bbox_{stride}"][0, i, 3] = math.log(height / stride)
    # Eyes, nose tip and mouth corners, in anchor cells from the anchor.
    outputs[f"kps_{stride}"][0, i] = [
        *(0.5, 0.25, 1.5, 0.25),
        *(1, 0.75),
        *(0.5, 1.25, 1.5, 1.25),
    ]
    return outputs


def test_the_strongest_face_maps_back_to_the_crop_and_a_weak_one_is_none():
    outputs = yunet()
    outputs["cls_8"][0, 0, 0] = outputs["obj_8"][0, 0, 0] = 0.7  # weaker elsewhere
    score, height, points = faces.best_face(outputs, (0, 80), 0.5)
    assert score == pytest.approx(0.9)
    assert height == pytest.approx(64)
    assert points[0] == pytest.approx(((20.5 * 16) / 0.5, (10.25 * 16 - 80) / 0.5))
    assert faces.best_face(yunet(score=0.5), (0, 0), 1.0) is None


def test_landmarks_on_the_template_need_no_warp():
    pixels = np.random.default_rng(1).integers(0, 255, (200, 200, 3), np.uint8)
    image = Image.fromarray(pixels)
    warped = np.asarray(faces.aligned(image, faces.TEMPLATE.copy()), dtype=float)
    assert np.abs(warped - pixels[:112, :112]).mean() < 1


def test_only_a_confident_face_of_some_size_describes_a_rider(monkeypatch):
    from app import vision

    engine = CpuVision.__new__(CpuVision)
    engine.reads_faces = True
    names = list(yunet())
    engine.sessions = {
        "face_detector": SimpleNamespace(
            get_outputs=lambda: [SimpleNamespace(name=n) for n in names]
        )
    }
    detected = {}

    def infer(key, tensor):
        if key == "people_detector":
            return []
        if key == "face_detector":
            assert tensor.shape == (1, 3, 640, 640)
            return [detected[n] for n in names]
        if key == "face_vectors":
            assert tensor.shape == (1, 3, 112, 112)
            return [np.array([[3.0, 4.0]])]
        return [np.ones((1, 768, 1, 1), dtype=np.float32)]

    engine._run = infer
    monkeypatch.setattr(vision, "person_boxes", lambda output: [(0.2, 0.0, 0.6, 1.0)])
    image = Image.new("RGB", (640, 640), "gray")
    detected.update(yunet(height=64))
    (rider,) = engine.riders(image)
    assert rider.face == pytest.approx([0.6, 0.8])
    detected.update(yunet(score=0.7, height=64))
    assert engine.riders(image)[0].face is None
    detected.update(yunet(height=8))  # a face a few pixels high
    assert engine.riders(image)[0].face is None
    engine.reads_faces = False
    assert engine.riders(image)[0].face is None
