"""Florence-2 decoding against fake ONNX sessions: no weights needed in CI."""

import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from app.florence import EOS, FIRST_LOCATION, Florence

ONE, ZERO = 10, 11  # token ids of "1" and "0" in the fake vocabulary


def location(fraction):
    return FIRST_LOCATION + round(fraction * 1000 - 0.5)


def corners(x, y, w, h):
    return [
        location(x),
        location(y),
        location(x + w),
        location(y),
        location(x + w),
        location(y + h),
        location(x),
        location(y + h),
    ]


class Session:
    def __init__(self, name, script=None):
        self.name = name
        self.script = list(script or [])
        self.seen = []

    def get_inputs(self):
        names = ["inputs_embeds", "past_key_values.0.decoder.key"]
        names += ["past_key_values.0.encoder.key", "use_cache_branch"]
        return [
            SimpleNamespace(name=n, shape=["batch", 12, "length", 64]) for n in names
        ]

    def get_outputs(self):
        names = ["logits", "present.0.decoder.key", "present.0.encoder.key"]
        return [SimpleNamespace(name=n) for n in names]

    def run(self, outputs, feeds):
        if self.name == "vision_encoder":
            assert feeds["pixel_values"].shape == (1, 3, 768, 768)
            return [np.zeros((1, 577, 8), dtype=np.float32)]
        if self.name == "embed_tokens":
            return [np.zeros((1, feeds["input_ids"].shape[1], 8), dtype=np.float32)]
        if self.name == "encoder_model":
            return [feeds["inputs_embeds"]]
        self.seen.append(feeds["past_key_values.0.decoder.key"].shape[2])
        logits = np.full((1, 1, 51289), -20.0)
        for rank, token in enumerate(self.script.pop(0)):
            logits[0, 0, token] = 20.0 - rank
        grown = self.seen[-1] + 1
        return [
            logits,
            np.zeros((1, 12, grown, 64), dtype=np.float32),
            np.zeros((1, 12, 5, 64), dtype=np.float32),
        ]


@pytest.fixture
def vocabulary(tmp_path):
    path = tmp_path / "tokenizer.json"
    added = [{"id": FIRST_LOCATION + k, "content": f"<loc_{k}>"} for k in range(1000)]
    vocab = {"<s>": 0, "<pad>": 1, "</s>": 2, "1": ONE, "0": ZERO, chr(0x120) + "x": 12}
    path.write_text(json.dumps({"model": {"vocab": vocab}, "added_tokens": added}))
    return path


def engine(vocabulary, script):
    sessions = {
        name: Session(name)
        for name in ("vision_encoder", "embed_tokens", "encoder_model")
    }
    sessions["decoder_model_merged"] = Session("decoder_model_merged", script)
    return Florence(sessions, vocabulary), sessions["decoder_model_merged"]


def test_a_text_with_its_box_is_read_after_the_forced_start(vocabulary):
    box = corners(0.25, 0.5, 0.1, 0.05)
    # Step 0 is the forced <s>, whatever the model scores; the rest is greedy.
    script = [[ZERO], [ONE], [ZERO], *[[t] for t in box], [EOS]]
    florence, decoder = engine(vocabulary, script)
    ((text, confidence, x, y, w, h),) = florence.read(Image.new("RGB", (40, 90)))
    assert text == "10"
    assert confidence == pytest.approx(1.0)
    assert (x, y, w, h) == pytest.approx((0.25, 0.5, 0.1, 0.05), abs=0.002)
    # The self-attention cache grows by one token a step.
    assert decoder.seen == list(range(len(script)))


def test_a_repeated_trigram_is_never_chosen(vocabulary):
    # Greedy would loop "1 0 1 0 1"; the third "1" after "1 0" repeats a trigram.
    script = [[ONE], [ONE], [ZERO], [ONE], [ZERO], [ONE, EOS], [EOS]]
    florence, _ = engine(vocabulary, script)
    assert florence.read(Image.new("RGB", (8, 8))) == []
    assert florence._decode([ONE, ZERO, ONE, ZERO]) == "1010"


def test_a_text_without_a_complete_box_is_dropped(vocabulary):
    florence, _ = engine(vocabulary, [])
    box = corners(0.1, 0.1, 0.2, 0.2)
    ids = [ONE, *box[:4], ZERO, *box, 12, *box]
    probabilities = [0.9, *[1.0] * 4, 0.6, *[1.0] * 8, 0.3, *[1.0] * 8]
    found = florence.texts(ids, probabilities)
    assert [(t[0], t[1]) for t in found] == [("0", 0.6), ("x", 0.3)]
