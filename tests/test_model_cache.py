"""Only verified pinned models reach the cache; cancellation leaves no partial file."""

import hashlib
import io

import pytest

from app import model_cache as cache


@pytest.fixture
def catalog(monkeypatch):
    payload = b"verified model"
    model = {
        "path": "models/test.onnx",
        "url": "https://example.test/test.onnx",
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


def test_offline_failure_cleans_up(tmp_path, monkeypatch, catalog):
    def offline(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(cache.urllib.request, "urlopen", offline)
    with pytest.raises(OSError, match="offline"):
        cache.ensure_models(False, lambda *a: None, lambda: False, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_larger_size_adds_its_own_models_to_the_small_set(
    tmp_path, monkeypatch, catalog
):
    monkeypatch.setattr(
        cache.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(catalog)
    )
    files = cache.ensure_models(
        False, lambda *a: None, lambda: False, tmp_path, "florence-2-large"
    )
    assert set(files) == {*cache.OCR_MODELS, *cache.SIZES["florence-2-large"]}
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
    # Two models under one file name would replace each other on every switch.
    names = {}
    for model in real.values():
        name = model["path"].rsplit("/", 1)[-1]
        assert names.setdefault(name, model["sha256"]) == model["sha256"]
    for key in (k for size in cache.SIZES.values() for k in size):
        assert real[key]["url"].startswith("https://huggingface.co/")
