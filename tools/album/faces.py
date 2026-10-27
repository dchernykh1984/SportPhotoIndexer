"""Find the same person on other photos of an album by face, to check by eye.

    uv run python -m tools.album.faces index ALBUM WORKDIR [MODELS]
    uv run python -m tools.album.faces like WORKDIR N X Y [MIN]

`index` finds people (the app's NanoDet), the best face in each one's head zone
(YuNet) and its 128-number SFace vector, and saves WORKDIR/people.npz. `like` takes
the person nearest to (X, Y), fractions of photo N, and lists every face in the album
at cosine similarity MIN (default 0.33) or more. SFace's own same-person threshold is
0.363; treat a hit as a lead to look at, never as an identification by itself.
Faces of people printed on banners match too.

Models download once into MODELS (default data/models): the app's OCR set (for the
person detector) and two OpenCV Zoo files, checked by size and SHA-256. Vectors stay
in WORKDIR; nothing is written into the album.
"""

from __future__ import annotations

import csv
import hashlib
import math
import sys
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app import vision
from app.model_cache import ensure_models

ZOO = (
    "https://media.githubusercontent.com/media/opencv/opencv_zoo/"
    "48b10fa505aeb51fbd127fc60a5c660040e823b7/models/"
)
FACE_MODELS = {
    "faces": (
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        232589,
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    "face_vectors": (
        "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        38696353,
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}
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
_sessions: dict = {}


def face_models(folder: Path) -> dict[str, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, (url, size, sha) in FACE_MODELS.items():
        path = folder / Path(url).name
        if not (path.exists() and path.stat().st_size == size):
            urllib.request.urlretrieve(ZOO + url, path)  # noqa: S310 -- pinned https
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            path.unlink()
            raise SystemExit(f"{path.name}: checksum mismatch, run again")
        paths[key] = path
    return paths


def _init(paths: dict[str, Path]) -> None:
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.log_severity_level = 3
    for key, path in paths.items():
        _sessions[key] = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"]
        )


def _run(key: str, tensor: np.ndarray) -> list:
    session = _sessions[key]
    return session.run(None, {session.get_inputs()[0].name: tensor})


def _people(image: Image.Image) -> list[vision.Region]:
    square, padding = vision._letterbox(image, 416)
    blob = vision._blob(
        square,
        (416, 416),
        (103.53, 116.28, 123.675),
        (57.375, 57.12, 58.395),
        bgr=True,
    )
    regions = (
        vision._unpad(p, padding, 416)
        for p in vision.person_boxes(_run("people_detector", blob))
    )
    return [r for r in regions if r is not None]


def _best_face(crop: Image.Image) -> tuple[float, float, np.ndarray] | None:
    """YuNet on the crop letterboxed to 640: score, face height, landmarks (crop px)."""
    square, (left, top, width, _) = vision._letterbox(crop, 640)
    scale = width / crop.width
    tensor = np.asarray(square, dtype=np.float32)[:, :, ::-1].transpose(2, 0, 1)[None]
    names = [o.name for o in _sessions["faces"].get_outputs()]
    out = dict(zip(names, _run("faces", np.ascontiguousarray(tensor)), strict=True))
    best = None
    for stride in (8, 16, 32):
        cols = 640 // stride
        score = np.sqrt(
            np.clip(out[f"cls_{stride}"][0, :, 0], 0, 1)
            * np.clip(out[f"obj_{stride}"][0, :, 0], 0, 1)
        )
        i = int(score.argmax())
        if score[i] < 0.6 or (best and score[i] <= best[0]):
            continue
        row, col = divmod(i, cols)
        box, kps = out[f"bbox_{stride}"][0, i], out[f"kps_{stride}"][0, i]
        points = (
            np.array([[kps[2 * k] + col, kps[2 * k + 1] + row] for k in range(5)])
            * stride
        )
        points = (points - (left, top)) / scale
        best = (float(score[i]), math.exp(box[3]) * stride / scale, points)
    return best


def _aligned(image: Image.Image, points: np.ndarray) -> Image.Image:
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


def _photo(args: tuple[Path, int, str]) -> list[tuple]:
    album, n, name = args
    with Image.open(album / name) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    width, height = image.size
    found = []
    for x, y, w, h in _people(image):
        head = image.crop(
            (
                max(0, (x - 0.1 * w) * width),
                max(0, (y - 0.05 * h) * height),
                min(width, (x + 1.1 * w) * width),
                min(height, (y + 0.45 * h) * height),
            )
        )
        face = _best_face(head) if min(head.size) >= 8 else None
        vector = np.zeros(128, np.float32)
        if face:
            tensor = np.asarray(_aligned(head, face[2]), dtype=np.float32)
            tensor = np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])
            raw = _run("face_vectors", tensor)[0].ravel()
            vector = raw / (np.linalg.norm(raw) or 1)
        found.append((n, (x, y, w, h), vector, face[0] if face else 0.0))
    return found


def index(album: Path, work: Path, models: Path) -> None:
    paths = ensure_models(False, lambda *a: None, lambda: False, cache=models)
    paths = {"people_detector": paths["people_detector"], **face_models(models)}
    with (work / "photos.csv").open(encoding="utf-8") as fh:
        rows = [(album, int(r[0]), r[1]) for r in csv.reader(fh)]
    with ProcessPoolExecutor(initializer=_init, initargs=(paths,)) as pool:
        people = [p for found in pool.map(_photo, rows) for p in found]
    np.savez(
        work / "people.npz",
        photo=np.array([p[0] for p in people]),
        region=np.array([p[1] for p in people]),
        face=np.stack([p[2] for p in people]),
        score=np.array([p[3] for p in people]),
    )
    print(f"{len(people)} people, {sum(p[3] > 0 for p in people)} with a face")


def like(work: Path, n: int, x: float, y: float, least: float) -> None:
    data = np.load(work / "people.npz")
    faces = [int(i) for i in np.flatnonzero(data["photo"] == n) if data["score"][i] > 0]
    if not faces:
        raise SystemExit(f"no face found on photo {n}")

    def distance(i: int) -> float:
        rx, ry, rw, rh = data["region"][i]
        return abs(rx + rw / 2 - x) + abs(ry + rh / 4 - y)

    query = data["face"][min(faces, key=distance)]
    hits = []
    for i in np.flatnonzero(data["score"] > 0):
        similarity = float(data["face"][i] @ query)
        if similarity >= least:
            rx, ry, rw, rh = data["region"][i]
            hits.append((similarity, int(data["photo"][i]), rx + rw / 2, ry + rh / 2))
    for similarity, photo, cx, cy in sorted(hits, reverse=True):
        print(f"{similarity:.2f}  photo {photo:4d}  person at {cx:.2f},{cy:.2f}")


if __name__ == "__main__":
    if sys.argv[1] == "index":
        models = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("data/models")
        index(Path(sys.argv[2]), Path(sys.argv[3]), models)
    else:
        least = float(sys.argv[6]) if len(sys.argv) > 6 else 0.33
        like(
            Path(sys.argv[2]),
            int(sys.argv[3]),
            float(sys.argv[4]),
            float(sys.argv[5]),
            least,
        )
