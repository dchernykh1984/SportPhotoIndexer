"""The model check fails exactly when a model would be lost without the mirror."""

import email.message
import errno
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


@pytest.fixture(autouse=True)
def any_file_is_verified(monkeypatch):
    # The fake downloads below write a file only where a source gave the model.
    monkeypatch.setattr(models, "verified", lambda key, path: path.exists())


@pytest.mark.parametrize(
    ("gone", "mirror", "upload"),
    [
        (set(), "empty", False),
        ({TWO}, "empty", False),  # ONE still gives it: not lost, nothing to upload
        ({ONE, TWO}, "empty", True),
        ({ONE, TWO}, "ok", False),
        (set(), "wrong", False),
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
        path.write_bytes(b"model")

    monkeypatch.setattr(models, "download_from", download)
    (tmp_path / "a.onnx").write_bytes(b"model")  # a verified copy from before
    # A dead source fails the check even when the mirror holds its model.
    assert models.main(tmp_path) == int(upload or bool(gone) or mirror == "wrong")
    out = capsys.readouterr().out
    command = f"gh release upload models-v1 {tmp_path / 'a.onnx'}"
    assert (command in out) == upload
    assert (tmp_path / "upload" / "a.onnx").exists() == upload  # for the artifact
    assert out.count("FAILED") == len(gone) + (mirror in ("wrong", "down"))
    assert all(f"\n  {url}\n" in out for url in gone)
    # A mirror that cannot be read may hold the model: no upload, but a look.
    assert ("could not be read" in out) == (mirror == "down")
    # Other bytes under the name may be what an installed app pins: never replaced.
    assert ("holds other bytes" in out) == (mirror == "wrong")
    assert "--clobber" not in out


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
            raise urllib.error.URLError(TimeoutError("timed out"))
        path.write_bytes(b"model")

    monkeypatch.setattr(models, "download_from", download)
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
        (model_cache.CutShortError("download ended early"), 3),
        (
            urllib.error.HTTPError(
                ONE, 503, "Unavailable", email.message.Message(), None
            ),
            3,
        ),
        (urllib.error.URLError(TimeoutError("The read operation timed out")), 3),
        (
            urllib.error.HTTPError(
                ONE, 429, "Too Many Requests", email.message.Message(), None
            ),
            3,
        ),
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

    monkeypatch.setattr(models, "download_from", download)
    models.main(tmp_path)
    assert calls.count(ONE) == tries


def test_a_full_disk_stops_the_check_instead_of_failing_every_source(
    tmp_path, monkeypatch
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE, TWO]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)
    calls = []

    def download(key, url, path, progress, cancel):
        calls.append(url)
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(models, "download_from", download)
    with pytest.raises(OSError, match="No space left"):
        models.main(tmp_path)
    assert calls == [ONE]


def test_the_upload_command_survives_a_folder_with_a_space(
    tmp_path, monkeypatch, capsys
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)

    def download(key, url, path, progress, cancel):
        if url.startswith(models.MIRROR):
            raise urllib.error.HTTPError(
                url, 404, "Not Found", email.message.Message(), None
            )
        raise model_cache.ModelError("download checksum does not match")

    monkeypatch.setattr(models, "download_from", download)
    path = tmp_path / "My Models" / "a.onnx"
    path.parent.mkdir()
    path.write_bytes(b"model")  # a verified copy from an earlier run
    models.main(tmp_path / "My Models")
    assert f"gh release upload models-v1 '{path}'" in capsys.readouterr().out


def test_what_to_do_about_a_model_is_said_before_the_next_model_is_checked(
    tmp_path, monkeypatch, capsys
):
    catalog = {
        "a": {"path": "dir/a.onnx", "urls": [ONE]},
        "b": {"path": "dir/b.onnx", "urls": ["https://three.test/b.onnx"]},
    }
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)

    def download(key, url, path, progress, cancel):
        if url.startswith(models.MIRROR):
            raise urllib.error.HTTPError(
                url, 404, "Not Found", email.message.Message(), None
            )
        if url == ONE:
            raise model_cache.ModelError("download checksum does not match")

    monkeypatch.setattr(models, "download_from", download)
    (tmp_path / "a.onnx").write_bytes(b"model")  # a verified copy from before
    models.main(tmp_path)
    out = capsys.readouterr().out
    next_model = out.index("https://three.test/b.onnx")
    assert (
        out.index(f"-> remove from app/model_catalog.json once it stays down: {ONE}")
        < next_model
    )
    assert (
        out.index(f"-> upload: gh release upload models-v1 {tmp_path / 'a.onnx'}")
        < next_model
    )
    assert "failed on every try" not in out


def test_a_lost_model_with_no_verified_copy_here_gets_no_upload_command(
    tmp_path, monkeypatch, capsys
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)

    def download(key, url, path, progress, cancel):
        if url.startswith(models.MIRROR):
            raise urllib.error.HTTPError(
                url, 404, "Not Found", email.message.Message(), None
            )
        raise model_cache.ModelError("download checksum does not match")

    monkeypatch.setattr(models, "download_from", download)
    assert models.main(tmp_path) == 1
    out = capsys.readouterr().out
    assert "gh release upload" not in out
    assert "no verified copy of a.onnx here" in out
    assert "the model is lost" in out


def test_a_source_slower_than_the_limit_is_cut_off_and_not_tried_again(
    tmp_path, monkeypatch, capsys
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)
    monkeypatch.setattr(models, "SLOWEST", -1)  # every download is past its time
    calls = []

    def download(key, url, path, progress, cancel):
        calls.append(url)
        if cancel():
            raise model_cache.CancelledError

    monkeypatch.setattr(models, "download_from", download)
    assert models.main(tmp_path) == 1
    assert calls.count(ONE) == 1
    assert f"FAILED {ONE}: slower than" in capsys.readouterr().out


def test_an_answer_that_comes_as_the_time_runs_out_is_reported_as_itself(
    tmp_path, monkeypatch, capsys
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)

    def download(key, url, path, progress, cancel):
        try:
            raise model_cache.ModelError("download checksum does not match")
        except model_cache.ModelError:
            # As download_from does when the time ran out during the hash.
            model_cache.check_cancel(lambda: True)
            raise

    monkeypatch.setattr(models, "download_from", download)
    models.main(tmp_path)
    out = capsys.readouterr().out
    assert f"FAILED {ONE}: download checksum does not match" in out
    assert "slower than" not in out


def test_a_check_out_of_time_names_the_models_it_did_not_reach(
    tmp_path, monkeypatch, capsys
):
    catalog = {"a": {"path": "dir/a.onnx", "urls": [ONE]}}
    monkeypatch.setattr(model_cache, "CATALOG", catalog)
    monkeypatch.setattr(models, "CATALOG", catalog)
    monkeypatch.setattr(models, "BUDGET", -1)
    calls = []
    monkeypatch.setattr(models, "download_from", lambda *args: calls.append(args))
    assert models.main(tmp_path) == 1
    assert calls == []
    assert "ran out of its time before these models" in capsys.readouterr().out
