"""The model check fails exactly when a model would be lost without the mirror."""

import email.message
import urllib.error

import pytest

from app import model_cache
from tools import models

ONE, TWO = "https://one.test/a.onnx", "https://two.test/a.onnx"


@pytest.mark.parametrize(
    ("gone", "mirror", "code"),
    [
        (set(), "empty", 0),
        ({TWO}, "empty", 1),
        ({ONE, TWO}, "ok", 0),
        (set(), "wrong", 1),
    ],
)
def test_the_check_asks_for_an_upload_only_when_the_mirror_lacks_a_lost_model(
    tmp_path, monkeypatch, capsys, gone, mirror, code
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE, TWO]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)

    def download(key, url, path, progress, cancel):
        if url.startswith(models.MIRROR) and mirror == "empty":
            raise urllib.error.HTTPError(
                url, 404, "Not Found", email.message.Message(), None
            )
        if url in gone or (url.startswith(models.MIRROR) and mirror == "wrong"):
            raise model_cache.ModelError("download checksum does not match")

    monkeypatch.setattr(models, "download", download)
    assert models.main(tmp_path) == code
    out = capsys.readouterr().out
    upload = "gh release upload models-v1 --clobber data/models/a.onnx"
    assert (upload in out) == bool(code)
    assert out.count("FAILED") == len(gone) + (mirror == "wrong")
