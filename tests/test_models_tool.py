"""The model check fails exactly when a model would be lost without the mirror."""

import email.message
import urllib.error

import pytest

from app import model_cache
from tools import models

ONE, TWO = "https://one.test/a.onnx", "https://two.test/a.onnx"


@pytest.fixture(autouse=True)
def pauses(monkeypatch):
    slept = []
    monkeypatch.setattr(models.time, "sleep", slept.append)
    return slept


@pytest.mark.parametrize(
    ("gone", "mirror", "upload"),
    [
        (set(), "empty", False),
        ({TWO}, "empty", True),
        ({ONE, TWO}, "ok", False),
        (set(), "wrong", True),
        ({ONE, TWO}, "down", False),
    ],
)
def test_the_check_asks_for_an_upload_only_when_the_mirror_lacks_a_lost_model(
    tmp_path, monkeypatch, capsys, gone, mirror, upload
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE, TWO]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)

    def download(key, url, path, progress, cancel):
        if url.startswith(models.MIRROR) and mirror == "empty":
            raise urllib.error.HTTPError(
                url, 404, "Not Found", email.message.Message(), None
            )
        if url.startswith(models.MIRROR) and mirror == "down":
            raise urllib.error.HTTPError(
                url, 503, "Unavailable", email.message.Message(), None
            )
        if url in gone or (url.startswith(models.MIRROR) and mirror == "wrong"):
            raise model_cache.ModelError("download checksum does not match")

    monkeypatch.setattr(models, "download", download)
    # A dead source fails the check even when the mirror holds its model.
    assert models.main(tmp_path) == int(upload or bool(gone))
    out = capsys.readouterr().out
    command = f"gh release upload models-v1 --clobber {tmp_path / 'a.onnx'}"
    assert (command in out) == upload
    assert out.count("FAILED") == len(gone) + (mirror in ("wrong", "down"))
    assert all(f"\n  {url}\n" in out for url in gone)
    # A mirror that cannot be read may hold the model: no upload, but a look.
    assert ("could not be read" in out) == (mirror == "down")


def test_a_source_that_fails_twice_is_tried_again_before_it_counts_as_lost(
    tmp_path, monkeypatch, capsys, pauses
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)
    calls = []

    def download(key, url, path, progress, cancel):
        calls.append(url)
        if calls.count(url) < 3:
            raise TimeoutError("timed out")

    monkeypatch.setattr(models, "download", download)
    assert models.main(tmp_path) == 0
    assert "FAILED" not in capsys.readouterr().out
    assert calls.count(ONE) == 3
    assert pauses[:2] == [30, 30]


@pytest.mark.parametrize(
    ("error", "tries"),
    [
        (
            urllib.error.HTTPError(
                ONE, 404, "Not Found", email.message.Message(), None
            ),
            1,
        ),
        (model_cache.ModelError("download checksum does not match"), 1),
        (
            urllib.error.HTTPError(
                ONE, 503, "Unavailable", email.message.Message(), None
            ),
            3,
        ),
        (urllib.error.URLError(TimeoutError("The read operation timed out")), 3),
    ],
)
def test_only_a_failure_that_may_pass_is_tried_again(
    tmp_path, monkeypatch, capsys, error, tries
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)
    calls = []

    def download(key, url, path, progress, cancel):
        calls.append(url)
        raise error

    monkeypatch.setattr(models, "download", download)
    models.main(tmp_path)
    assert calls.count(ONE) == tries
