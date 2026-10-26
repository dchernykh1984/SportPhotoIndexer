"""Settings are kept next to the downloaded program, not where it was started from."""

from __future__ import annotations

import pytest

from app import paths, settings


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    home = tmp_path / "program"
    home.mkdir()
    elsewhere = tmp_path / "working"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        paths.sys,
        "executable",
        str(home / "SportPhotoIndexer.app/Contents/MacOS/SportPhotoIndexer"),
    )
    return home


def test_settings_live_next_to_the_app(app_dir):
    settings.save({"folder": "/photos/race"})
    assert (app_dir / "data" / "spi_settings.json").exists()
    assert settings.load() == {"folder": "/photos/race"}


def test_a_broken_settings_file_reads_as_empty(app_dir):
    (app_dir / "data").mkdir()
    (app_dir / "data" / "spi_settings.json").write_text("{oops", encoding="utf-8")
    assert settings.load() == {}
