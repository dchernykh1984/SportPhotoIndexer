"""Pinned, verified CPU models; only model files leave the network, never photos."""

from __future__ import annotations

import hashlib
import json
import math
import ssl
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

import certifi

from app.paths import app_path

CATALOG = json.loads(
    Path(__file__).with_name("model_catalog.json").read_text(encoding="utf-8")
)
# OCR reads bibs around the people it finds, so the person detector belongs to it.
OCR_MODELS = ("text_detector", "text_reader", "people_detector")
ALL_MODELS = (*OCR_MODELS, "appearance")


def download_megabytes(appearance: bool) -> int:
    keys = ALL_MODELS if appearance else OCR_MODELS
    return math.ceil(sum(CATALOG[key]["bytes"] for key in keys) / 1_000_000)


class CancelledError(Exception):
    pass


class ModelError(ValueError):
    pass


def check_cancel(cancel: Callable[[], bool]) -> None:
    if cancel():
        raise CancelledError


def _digest(path: Path, cancel: Callable[[], bool]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest()


def ensure_models(
    appearance: bool,
    progress: Callable[[str, int, int], None],
    cancel: Callable[[], bool],
    cache: Path | None = None,
) -> dict[str, Path]:
    cache = cache if cache is not None else app_path("data/models")
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    for key in ALL_MODELS if appearance else OCR_MODELS:
        check_cancel(cancel)
        model = CATALOG[key]
        path = cache / Path(model["path"]).name
        if not (
            path.exists()
            and path.stat().st_size == model["bytes"]
            and _digest(path, cancel) == model["sha256"]
        ):
            _download(key, path, progress, cancel)
        result[key] = path
    return result


def _download(key, path, progress, cancel) -> None:
    model = CATALOG[key]
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            tmp = Path(stream.name)
            context = ssl.create_default_context(cafile=certifi.where())
            # URLs are fixed HTTPS entries in the committed catalog.
            with urllib.request.urlopen(  # noqa: S310
                model["url"], timeout=15, context=context
            ) as response:
                size = 0
                while chunk := response.read(64 * 1024):
                    check_cancel(cancel)
                    size += len(chunk)
                    if size > model["bytes"]:
                        raise ModelError(f"{key}: download exceeds the expected size")
                    stream.write(chunk)
                    progress(f"Downloading {key}", size, model["bytes"])
        if size != model["bytes"] or _digest(tmp, cancel) != model["sha256"]:
            raise ModelError(f"{key}: download checksum does not match; retry")
        tmp.replace(path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
