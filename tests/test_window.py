"""The window drives the whole manual job: open a folder, type bibs, Enter, next."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app import indexer, settings
from app import main_window as mw

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def win(monkeypatch, tmp_path):
    store: dict = {}
    monkeypatch.setattr(settings, "load", lambda: dict(store))
    monkeypatch.setattr(settings, "save", lambda values: store.update(values))
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: None)
    w = mw.MainWindow()
    yield w
    w.deleteLater()


def test_typing_bibs_and_enter_saves_and_moves_on(win, album):
    win.open_folder(album)
    assert win._list.count() == 3
    assert win._list.currentRow() == 0
    win._edit_bibs.setText("12 7")
    win._on_enter()
    assert win._list.currentRow() == 1
    assert indexer.bibs_of(indexer.load(album)["photos"][0]) == ["12", "7"]
    win._edit_bibs.setText("")
    win._on_enter()  # a photo with nobody's bib is checked too
    saved = indexer.load(album)
    assert saved["processing"]["processed"] == 2
    assert "2 checked" in win._lbl_status.text()


def test_reopening_starts_at_the_first_unchecked_photo(win, album):
    win.open_folder(album)
    win._edit_bibs.setText("1")
    win._on_enter()
    win.open_folder(album)
    assert win._list.currentRow() == 1
    assert "1" in win._list.item(0).text()


def test_a_refused_bib_is_explained_and_nothing_moves(win, album):
    win.open_folder(album)
    win._edit_bibs.setText("x" * 40)
    win._on_enter()
    assert win._list.currentRow() == 0
    assert "1 to 32" in win._lbl_status.text()


def test_the_last_folder_is_reopened(monkeypatch, album):
    monkeypatch.setattr(settings, "load", lambda: {"folder": str(album)})
    monkeypatch.setattr(settings, "save", lambda values: None)
    w = mw.MainWindow()
    assert w._list.count() == 3
    w.deleteLater()


def test_a_broken_photo_does_not_escape_rescan_or_replace_the_open_album(
    win, album, monkeypatch
):
    win.open_folder(album)
    before = indexer.load(album)
    (album / "broken.jpg").write_text("not an image", encoding="utf-8")
    win._chk_previews.setChecked(True)
    warnings = []
    monkeypatch.setattr(
        mw.QMessageBox, "warning", lambda *args: warnings.append(str(args[-1]))
    )
    win.rescan()
    assert warnings and "broken.jpg" in warnings[0]
    assert win._index == before
    assert indexer.load(album) == before
    assert win._list.count() == 3


def test_an_unreadable_last_folder_does_not_prevent_starting(monkeypatch, album):
    monkeypatch.setattr(settings, "load", lambda: {"folder": str(album)})
    monkeypatch.setattr(settings, "save", lambda values: None)
    monkeypatch.setattr(
        indexer,
        "sha256_of",
        lambda path: (_ for _ in ()).throw(OSError("offline file")),
    )
    warnings = []
    monkeypatch.setattr(
        mw.QMessageBox, "warning", lambda *args: warnings.append(str(args[-1]))
    )
    w = mw.MainWindow()
    assert warnings and "offline file" in warnings[0]
    assert w._folder is None
    assert w._list.count() == 0
    w.deleteLater()
