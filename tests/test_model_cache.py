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
    monkeypatch.setattr(cache, "CATALOG", {k: model for k in cache.ALL_MODELS})
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
