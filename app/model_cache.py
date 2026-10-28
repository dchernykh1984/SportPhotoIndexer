"""Pinned, verified CPU models; only model files leave the network, never photos."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import math
import socket
import ssl
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

import certifi

from app.paths import app_path

CATALOG = json.loads(
    Path(__file__).with_name("model_catalog.json").read_text(encoding="utf-8")
)
# The last source of every model: a release of this repository that holds a model only
# once its own sources have lost it (tools/models.py), so even a copy of the app that
# is already installed finds it there.
MIRROR = (
    "https://github.com/dchernykh1984/SportPhotoIndexer/releases/download/models-v1/"
)
# OCR reads bibs around the people it finds, so the person detector belongs to it.
OCR_MODELS = ("text_detector", "text_reader", "people_detector")
ALL_MODELS = (*OCR_MODELS, "appearance")
# Only the "appearance and faces" mode downloads these.
FACE_MODELS = ("face_detector", "face_vectors")
_FLORENCE = ("vision_encoder", "embed_tokens", "encoder_model", "decoder_model_merged")
# Larger sizes add Florence-2, which reads bibs the small reader misses; each size
# is offered only while it finds more (docs/recognition-benchmark.md).
SIZES = {
    "small": (),
    **{
        size: (*(f"{size}/{part}" for part in _FLORENCE), "florence-2/tokenizer")
        for size in ("florence-2-base-int8", "florence-2-base")
    },
}


def ocr_models(size: str = "small") -> tuple[str, ...]:
    return (*OCR_MODELS, *SIZES[size])


def _keys(appearance: bool, size: str, faces: bool) -> tuple[str, ...]:
    return (
        *ocr_models(size),
        *(("appearance",) if appearance else ()),
        *(FACE_MODELS if faces else ()),
    )


def download_megabytes(
    appearance: bool, size: str = "small", faces: bool = False
) -> int:
    keys = _keys(appearance, size, faces)
    return math.ceil(sum(CATALOG[key]["bytes"] for key in keys) / 1_000_000)


class CancelledError(Exception):
    pass


class ModelError(ValueError):
    pass


class CutShortError(ModelError):
    """The connection closed before the whole file arrived; urllib hands over the
    shorter body without an error."""


# How a source fails (_read reports the network failing mid-file the same way). A full
# or read-only disk fails every source alike, so it stops the download at once and is
# reported as itself.
SOURCE_ERRORS = (urllib.error.URLError, http.client.HTTPException, ModelError)


# A host gets 15 seconds to connect; once connected, a source gets a minute without
# data, its headers included: ModelScope pauses longer than 15 seconds in the middle of
# a file when it is far away, while a host that drops packets must not hold every
# source for a minute.
CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60


class _Response(http.client.HTTPResponse):
    """Keeps its socket, so that Stop can end a read that waits for data."""

    def __init__(self, sock: socket.socket, *args, **kwargs) -> None:
        super().__init__(sock, *args, **kwargs)
        self.socket = sock


class _Connection(http.client.HTTPSConnection):
    response_class = _Response

    def connect(self) -> None:
        super().connect()
        self.sock.settimeout(READ_TIMEOUT)


class _Handler(urllib.request.HTTPSHandler):
    def __init__(self, context: ssl.SSLContext) -> None:
        # Given the context, the base class builds no default one of its own.
        super().__init__(context=context)
        self.ssl_context = context

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(_Connection, req, context=self.ssl_context)


def _open(url: str) -> _Response:
    context = ssl.create_default_context(cafile=certifi.where())
    opener = urllib.request.build_opener(_Handler(context))
    try:
        # URLs are fixed HTTPS entries in the committed catalog.
        return opener.open(url, timeout=CONNECT_TIMEOUT)
    except urllib.error.HTTPError as exc:
        exc.close()  # its response would hold the connection until collected
        raise
    except urllib.error.URLError:
        raise
    except OSError as exc:  # urllib leaves a failure awaiting the headers bare
        raise urllib.error.URLError(exc) from exc


def _read(response: http.client.HTTPResponse) -> bytes:
    """The next piece of a download; the network failing in the middle of the file is
    reported the way urllib reports it failing before the first byte."""
    try:
        return response.read(64 * 1024)
    except OSError as exc:
        raise urllib.error.URLError(exc) from exc


def _end_on_stop(
    response: _Response,
    cancel: Callable[[], bool],
    done: threading.Event,
) -> None:
    """Shut the socket of a read waiting for data once Stop is pressed: the download
    then ends at once, not after a minute of the read timeout."""
    while not done.wait(0.2):
        if cancel():
            # A response without the socket (plain HTTP after a redirect) runs out
            # its read timeout instead.
            with contextlib.suppress(AttributeError, OSError):
                response.socket.shutdown(socket.SHUT_RDWR)
            return


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
    size: str = "small",
    faces: bool = False,
) -> dict[str, Path]:
    cache = cache if cache is not None else app_path("data/models")
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    for key in _keys(appearance, size, faces):
        check_cancel(cancel)
        model = CATALOG[key]
        path = cache / file_name(key)
        if not (
            path.exists()
            and path.stat().st_size == model["bytes"]
            and _digest(path, cancel) == model["sha256"]
        ):
            _download_any(key, path, progress, cancel)
        result[key] = path
    return result


def file_name(key: str) -> str:
    """The model's file in the cache, and in the mirror release."""
    return Path(CATALOG[key]["path"]).name


def sources(key: str) -> tuple[str, ...]:
    """The catalog's sources of the model, then this repository's mirror."""
    return (*CATALOG[key]["urls"], MIRROR + file_name(key))


def _download_any(key, path, progress, cancel) -> None:
    # The sources after the first are byte-identical copies, so a source that is down
    # or has lost the file costs one request instead of the model.
    failed = []
    for url in sources(key):
        check_cancel(cancel)  # Stop pressed while a source failed opens no other one
        try:
            download_from(key, url, path, progress, cancel)
            return
        except SOURCE_ERRORS as exc:
            failed.append(f"{urllib.parse.urlsplit(url).netloc}: {exc}")
    raise ModelError("\n".join([f"{key}: every source failed; retry", *failed]))


def download_from(
    key: str,
    url: str,
    path: Path,
    progress: Callable[[str, int, int], None],
    cancel: Callable[[], bool],
) -> None:
    """Fetch one source of the model; only a file of its pinned size and hash lands."""
    model = CATALOG[key]
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            tmp = Path(stream.name)
            with _open(url) as response:
                done = threading.Event()
                watch = (response, cancel, done)
                threading.Thread(target=_end_on_stop, args=watch, daemon=True).start()
                try:
                    size = 0
                    while chunk := _read(response):
                        check_cancel(cancel)
                        size += len(chunk)
                        if size > model["bytes"]:
                            raise ModelError("download exceeds the expected size")
                        stream.write(chunk)
                        progress(f"Downloading {key}", size, model["bytes"])
                finally:
                    done.set()
        if size < model["bytes"]:
            raise CutShortError("download ended early")
        if _digest(tmp, cancel) != model["sha256"]:
            raise ModelError("download checksum does not match")
        tmp.replace(path)
    except SOURCE_ERRORS:
        check_cancel(cancel)  # a read that Stop ended is a Stop, not a failing source
        raise
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
