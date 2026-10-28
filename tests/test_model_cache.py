"""Only verified pinned models reach the cache; cancellation leaves no partial file."""

import email.message
import errno
import hashlib
import http.client
import io
import re
import urllib.error

import pytest

from app import model_cache as cache


@pytest.fixture
def catalog(monkeypatch):
    payload = b"verified model"
    model = {
        "path": "models/test.onnx",
        "urls": ["https://example.test/test.onnx", "https://copy.test/test.onnx"],
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    keys = {*cache.ALL_MODELS, *cache.FACE_MODELS}
    keys |= {k for size in cache.SIZES.values() for k in size}
    monkeypatch.setattr(cache, "CATALOG", {k: model for k in keys})
    return payload


def test_downloaded_models_are_verified_reused_and_progress_is_visible(
    tmp_path, monkeypatch, catalog
):
    calls, updates = [], []

    def open_url(url, **kwargs):
        calls.append(url)
        assert kwargs["context"].verify_mode
        assert kwargs["timeout"] >= 60  # a far source pauses mid-file
        return io.BytesIO(catalog)

    monkeypatch.setattr(cache.urllib.request, "urlopen", open_url)
    files = cache.ensure_models(
        True, lambda *args: updates.append(args), lambda: False, tmp_path
    )
    assert set(files) == set(cache.ALL_MODELS)
    assert len(calls) == 1  # all fixture entries intentionally share one file
    assert updates[0][1:] == (len(catalog), len(catalog))
    cache.ensure_models(False, lambda *args: None, lambda: False, tmp_path)
    assert len(calls) == 1


@pytest.mark.parametrize("payload", [b"short", b"wrong model!!!", b"x" * 100])
def test_bad_downloads_never_replace_the_cached_model(
    tmp_path, monkeypatch, catalog, payload
):
    old = tmp_path / "test.onnx"
    old.write_bytes(b"old model")
    monkeypatch.setattr(
        cache.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(payload)
    )
    with pytest.raises(cache.ModelError):
        cache.ensure_models(False, lambda *a: None, lambda: False, tmp_path)
    assert old.read_bytes() == b"old model"
    assert list(tmp_path.iterdir()) == [old]


def test_cancel_interrupts_download_and_cleans_up(tmp_path, monkeypatch, catalog):
    monkeypatch.setattr(
        cache.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(catalog)
    )
    stopped = False

    def progress(*args):
        nonlocal stopped
        stopped = True

    with pytest.raises(cache.CancelledError):
        cache.ensure_models(False, progress, lambda: stopped, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_offline_failure_names_every_source_and_cleans_up(
    tmp_path, monkeypatch, catalog
):
    def offline(*args, **kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(cache.urllib.request, "urlopen", offline)
    with pytest.raises(cache.ModelError) as failure:
        cache.ensure_models(False, lambda *a: None, lambda: False, tmp_path)
    for host in ("example.test", "copy.test", "github.com"):
        assert f"{host}: <urlopen error offline>" in str(failure.value)
    assert list(tmp_path.iterdir()) == []


def test_a_full_disk_stops_the_download_instead_of_trying_every_source(
    tmp_path, monkeypatch, catalog
):
    calls = []

    def full(*args, **kwargs):
        calls.append(args)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(cache.tempfile, "NamedTemporaryFile", full)
    with pytest.raises(OSError, match="No space left"):
        cache.ensure_models(False, lambda *a: None, lambda: False, tmp_path)
    assert len(calls) == 1


def test_the_repository_mirror_is_the_last_source(tmp_path, monkeypatch, catalog):
    calls = []

    def open_url(url, **kwargs):
        calls.append(url)
        if not url.startswith(cache.MIRROR):
            raise urllib.error.URLError("gone")
        return io.BytesIO(catalog)

    monkeypatch.setattr(cache.urllib.request, "urlopen", open_url)
    files = cache.ensure_models(False, lambda *a: None, lambda: False, tmp_path)
    assert calls[-1] == cache.MIRROR + "test.onnx" and len(calls) == 3
    assert files["text_reader"].read_bytes() == catalog


class _Dropped(io.BytesIO):
    def read(self, *args):
        raise http.client.IncompleteRead(b"")


@pytest.mark.parametrize(
    "first",
    [
        urllib.error.HTTPError(
            "https://example.test", 404, "Not Found", email.message.Message(), None
        ),
        urllib.error.URLError("host not found"),
        TimeoutError("timed out"),
        io.BytesIO(b"wrong model!!!"),
        _Dropped(),
    ],
)
def test_a_failing_source_falls_back_to_the_next_copy(
    tmp_path, monkeypatch, catalog, first
):
    calls = []

    def open_url(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            if isinstance(first, Exception):
                raise first
            return first
        return io.BytesIO(catalog)

    monkeypatch.setattr(cache.urllib.request, "urlopen", open_url)
    files = cache.ensure_models(False, lambda *a: None, lambda: False, tmp_path)
    assert calls == ["https://example.test/test.onnx", "https://copy.test/test.onnx"]
    assert files["text_reader"].read_bytes() == catalog
    assert list(tmp_path.iterdir()) == [files["text_reader"]]


def test_a_larger_size_adds_its_own_models_to_the_small_set(
    tmp_path, monkeypatch, catalog
):
    monkeypatch.setattr(
        cache.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(catalog)
    )
    files = cache.ensure_models(
        False, lambda *a: None, lambda: False, tmp_path, "florence-2-base"
    )
    assert set(files) == {*cache.OCR_MODELS, *cache.SIZES["florence-2-base"]}
    assert "appearance" not in files


def test_faces_add_only_the_two_face_models(tmp_path, monkeypatch, catalog):
    monkeypatch.setattr(
        cache.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(catalog)
    )
    files = cache.ensure_models(
        True, lambda *a: None, lambda: False, tmp_path, faces=True
    )
    assert set(files) == {*cache.ALL_MODELS, *cache.FACE_MODELS}


def test_every_size_downloads_more_and_keeps_its_files_apart():
    real = cache.CATALOG
    sizes = [cache.download_megabytes(False, size) for size in cache.SIZES]
    assert sizes == sorted(sizes) and len(set(sizes)) == len(sizes)
    assert cache.download_megabytes(True, faces=True) > cache.download_megabytes(True)
    # Two models under one file name would replace each other on every switch, and
    # in the mirror; GitHub renames a release file with other characters in its name.
    names = {}
    for model in real.values():
        name = model["path"].rsplit("/", 1)[-1]
        assert names.setdefault(name, model["sha256"]) == model["sha256"]
        assert re.fullmatch(r"[A-Za-z0-9._-]+", name)
    for key in (k for size in cache.SIZES.values() for k in size):
        assert real[key]["urls"][0].startswith("https://huggingface.co/")
    # HTTPS only; a copy is trusted for its hash, not for its host.
    for model in real.values():
        assert model["urls"] and all(u.startswith("https://") for u in model["urls"])
