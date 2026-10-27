"""A rider's face for appearance matching: YuNet finds it, SFace describes it.

Both are pinned OpenCV Zoo models (see licenses/ and MODEL_NOTICES.md). The face is
looked for only in the head zone of a person the person detector found, and its
vector lives as long as one recognition run, like the body vectors.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image

# ArcFace's five-point template for a 112x112 face: eyes, nose tip, mouth corners.
TEMPLATE = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ]
)


def head_box(region, size):
    """The top of a person's box, a little wider: where their face is."""
    x, y, w, h = region
    width, height = size
    return (
        max(0, (x - 0.1 * w) * width),
        max(0, (y - 0.05 * h) * height),
        min(width, (x + 1.1 * w) * width),
        min(height, (y + 0.45 * h) * height),
    )


def best_face(outputs: dict, padding, scale: float):
    """YuNet's most confident face on a 640 letterbox: score, height, landmarks.

    Height and landmarks are in pixels of the crop that was letterboxed.
    """
    left, top = padding
    best = None
    for stride in (8, 16, 32):
        cols = 640 // stride
        score = np.sqrt(
            np.clip(outputs[f"cls_{stride}"][0, :, 0], 0, 1)
            * np.clip(outputs[f"obj_{stride}"][0, :, 0], 0, 1)
        )
        i = int(score.argmax())
        if score[i] < 0.6 or (best and score[i] <= best[0]):
            continue
        row, col = divmod(i, cols)
        box, kps = outputs[f"bbox_{stride}"][0, i], outputs[f"kps_{stride}"][0, i]
        points = (
            np.array([[kps[2 * k] + col, kps[2 * k + 1] + row] for k in range(5)])
            * stride
        )
        points = (points - (left, top)) / scale
        best = (float(score[i]), math.exp(box[3]) * stride / scale, points)
    return best


def aligned(image: Image.Image, points: np.ndarray) -> Image.Image:
    """Similarity transform (Umeyama) of the landmarks onto the template."""
    mu_s, mu_d = points.mean(0), TEMPLATE.mean(0)
    src, dst = points - mu_s, TEMPLATE - mu_d
    u, d, vt = np.linalg.svd(dst.T @ src / 5)
    sign = np.ones(2)
    sign[1] = np.sign(np.linalg.det(u) * np.linalg.det(vt))
    rotation = u @ np.diag(sign) @ vt
    a = (d * sign).sum() / src.var(0).sum() * rotation
    inverse = np.linalg.inv(a)
    shift = -inverse @ (mu_d - a @ mu_s)
    return image.transform(
        (112, 112),
        Image.Transform.AFFINE,
        (*inverse[0], shift[0], *inverse[1], shift[1]),
        resample=Image.Resampling.BILINEAR,
    )
