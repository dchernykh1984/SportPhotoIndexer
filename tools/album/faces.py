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
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app import faces, vision
from app.model_cache import ensure_models

_sessions: dict = {}


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
    tensor = np.asarray(square, dtype=np.float32)[:, :, ::-1].transpose(2, 0, 1)[None]
    names = [o.name for o in _sessions["face_detector"].get_outputs()]
    outputs = _run("face_detector", np.ascontiguousarray(tensor))
    return faces.best_face(
        dict(zip(names, outputs, strict=True)), (left, top), width / crop.width
    )


def _photo(args: tuple[Path, int, str]) -> list[tuple]:
    album, n, name = args
    with Image.open(album / name) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    found = []
    for x, y, w, h in _people(image):
        head = image.crop(faces.head_box((x, y, w, h), image.size))
        face = _best_face(head) if min(head.size) >= 8 else None
        vector = np.zeros(128, np.float32)
        if face:
            tensor = np.asarray(faces.aligned(head, face[2]), dtype=np.float32)
            tensor = np.ascontiguousarray(tensor.transpose(2, 0, 1)[None])
            raw = _run("face_vectors", tensor)[0].ravel()
            vector = raw / (np.linalg.norm(raw) or 1)
        found.append((n, (x, y, w, h), vector, face[0] if face else 0.0))
    return found


def index(album: Path, work: Path, models: Path) -> None:
    paths = ensure_models(False, lambda *a: None, lambda: False, models, faces=True)
    paths = {k: paths[k] for k in ("people_detector", "face_detector", "face_vectors")}
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
