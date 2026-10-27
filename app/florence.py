"""Florence-2 text reading with ONNX Runtime and NumPy, for the larger model sets.

The onnx-community export splits the model in four: vision encoder, token embedding,
text encoder and a decoder with a key/value cache. The task is OCR_WITH_REGION: the
model writes each text it sees followed by eight location tokens, the corners of
its box in thousandths of the crop. Generation follows the model's own settings:
`<s>` forced first, then greedy decoding that never repeats a token trigram.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

# "<s>What is the text in the image, with regions?</s>", as the processor encodes it.
PROMPT = [0, 2264, 16, 5, 2788, 11, 5, 2274, 6, 19, 3806, 116, 2]
START, BOS, PAD, EOS = 2, 0, 1, 2
FIRST_LOCATION, LAST_LOCATION = 50269, 51268
PARTS = ("vision_encoder", "embed_tokens", "encoder_model", "decoder_model_merged")


def _byte_decoder() -> dict[str, int]:
    """GPT-2's byte-level BPE alphabet, reversed: one printable character per byte."""
    printable = [*range(33, 127), *range(161, 173), *range(174, 256)]
    chars = list(printable)
    extra = 0
    for byte in range(256):
        if byte not in printable:
            printable.append(byte)
            chars.append(256 + extra)
            extra += 1
    return {chr(c): b for b, c in zip(printable, chars, strict=True)}


class Florence:
    def __init__(self, sessions: dict, vocabulary: Path) -> None:
        self.sessions = sessions
        data = json.loads(vocabulary.read_text(encoding="utf-8"))
        self.tokens = {i: t for t, i in data["model"]["vocab"].items()}
        for added in data.get("added_tokens", []):
            self.tokens[added["id"]] = added["content"]
        self.bytes = _byte_decoder()
        decoder = sessions["decoder_model_merged"]
        self.past = [i.name for i in decoder.get_inputs() if i.name.startswith("past")]
        self.outputs = [o.name for o in decoder.get_outputs()]
        heads = next(i.shape[1] for i in decoder.get_inputs() if i.name in self.past)
        self.heads = heads if isinstance(heads, int) else 16

    def _run(self, part: str, feeds: dict) -> list:
        return self.sessions[part].run(None, feeds)

    def _embed(self, ids: list[int]) -> np.ndarray:
        return self._run(
            "embed_tokens", {"input_ids": np.array([ids], dtype=np.int64)}
        )[0]

    def read(self, image: Image.Image, limit: int = 256) -> list[tuple]:
        """Texts on the image: (text, lowest token probability, x, y, w, h)."""
        rgb = np.asarray(
            image.convert("RGB").resize((768, 768), Image.Resampling.BICUBIC),
            dtype=np.float32,
        )
        pixels = (rgb / 255 - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
        features = self._run(
            "vision_encoder",
            {"pixel_values": pixels.transpose(2, 0, 1)[None].astype(np.float32)},
        )[0]
        embeds = np.concatenate([features, self._embed(PROMPT)], axis=1)
        mask = np.ones(embeds.shape[:2], dtype=np.int64)
        hidden = self._run(
            "encoder_model", {"inputs_embeds": embeds, "attention_mask": mask}
        )[0]
        past = {
            name: np.zeros((1, self.heads, 0, 64), dtype=np.float32)
            for name in self.past
        }
        token = START
        generated: list[int] = []
        probabilities: list[float] = []
        for step in range(limit):
            feeds = {
                "inputs_embeds": self._embed([token]),
                "encoder_hidden_states": hidden,
                "encoder_attention_mask": mask,
                "use_cache_branch": np.array([step > 0]),
                **past,
            }
            out = dict(
                zip(self.outputs, self._run("decoder_model_merged", feeds), strict=True)
            )
            for name in self.past:
                # Cross-attention keys come once; self-attention keys grow every step.
                if step == 0 or ".decoder." in name:
                    past[name] = out[name.replace("past_key_values", "present")]
            if step == 0:
                token = BOS
                continue
            logits = out["logits"][0, -1].astype(np.float64)
            p = np.exp(logits - logits.max())
            p /= p.sum()
            history = [START, BOS, *generated]
            choice = p.copy()
            for i in range(len(history) - 2):
                if history[i : i + 2] == history[-2:]:
                    choice[history[i + 2]] = 0
            token = int(choice.argmax())
            if token == EOS:
                break
            generated.append(token)
            probabilities.append(float(p[token]))
        return self.texts(generated, probabilities)

    def _decode(self, ids: list[int]) -> str:
        raw = "".join(self.tokens.get(i, "") for i in ids)
        return (
            bytes(self.bytes.get(c, 32) for c in raw).decode("utf-8", "replace").strip()
        )

    def texts(self, ids: list[int], probabilities: list[float]) -> list[tuple]:
        found: list[tuple] = []
        text: list[int] = []
        scores: list[float] = []
        corners: list[float] = []
        for token, p in zip(ids, probabilities, strict=True):
            if FIRST_LOCATION <= token <= LAST_LOCATION:
                corners.append((token - FIRST_LOCATION + 0.5) / 1000)
                if len(corners) == 8:
                    label = self._decode(text)
                    if label:
                        xs, ys = corners[0::2], corners[1::2]
                        box = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
                        found.append((label, min(scores), *box))
                    text, scores, corners = [], [], []
            elif token not in (BOS, PAD):
                if corners:  # a location run cut short: drop the partial text
                    text, scores, corners = [], [], []
                text.append(token)
                scores.append(p)
        return found
