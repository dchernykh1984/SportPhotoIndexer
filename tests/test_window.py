"""The window drives the whole manual job: open a folder, type bibs, Enter, next."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app import indexer, recognition, settings
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


def test_a_failed_csv_save_does_not_claim_success_or_change_the_open_index(
    win, album, monkeypatch, tmp_path
):
    win.open_folder(album)
    before = indexer.load(album)
    table = tmp_path / "bibs.csv"
    table.write_text("file;bibs\nIMG_0001.jpg;12\n", encoding="utf-8")
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileName", lambda *args: (str(table), "")
    )

    def refuse(*args):
        raise indexer.StaleIndexError("changed elsewhere")

    monkeypatch.setattr(indexer, "save", refuse)
    successes = []
    monkeypatch.setattr(
        mw.QMessageBox, "information", lambda *args: successes.append(args)
    )
    win._on_import_csv()
    assert successes == []
    assert win._index == before
    assert indexer.load(album) == before


def test_a_failed_rescan_save_keeps_the_previous_index_and_list(
    win, album, monkeypatch
):
    from tests.conftest import make_photo

    win.open_folder(album)
    before = indexer.load(album)
    make_photo(album, "new.jpg")

    def refuse(*args):
        raise OSError("disk full")

    monkeypatch.setattr(indexer, "save", refuse)
    assert win.rescan() is False
    assert win._index == before
    assert win._list.count() == 3


@pytest.mark.parametrize("appearance", [True, False])
def test_one_button_runs_the_selected_automatic_stages_and_reloads_saved_results(
    win, album, monkeypatch, appearance
):
    from contextlib import nullcontext

    from app import recognition_worker as worker_module
    from tests.test_recognition import FakeVision

    engine = FakeVision()
    monkeypatch.setattr(worker_module, "ensure_models", lambda *args, **kwargs: {})
    monkeypatch.setattr(worker_module, "PhotoPool", lambda *args: nullcontext(engine))
    win.open_folder(album)
    assert win._mode.currentIndex() == 1
    assert not win._btn_stop.isEnabled()
    if not appearance:
        win._mode.setCurrentIndex(0)
    win._on_recognize()
    thread = win._worker
    assert thread is not None
    assert not win._btn_auto.isEnabled() and not win._btn_open.isEnabled()
    assert win._btn_stop.isEnabled()
    assert thread.wait(10000)
    _app.processEvents()
    assert win._worker is None
    assert win._btn_auto.isEnabled() and win._btn_open.isEnabled()
    assert not win._btn_stop.isEnabled()
    if appearance:
        assert ("riders", 0) in engine.calls
        assert "check: 012" in win._list.item(1).text()
    else:
        assert all(kind == "ocr" for kind, _ in engine.calls)
    assert win._index == indexer.load(album)
    assert "Recognition finished" in win._lbl_status.text()


def test_the_search_mode_and_model_size_can_be_chosen_before_an_album(win):
    assert win._mode.isEnabled() and win._size.isEnabled()
    assert not win._btn_auto.isEnabled()


def test_the_chosen_model_size_is_downloaded_used_and_remembered(
    win, album, monkeypatch
):
    from contextlib import nullcontext

    from app import recognition_worker as worker_module
    from tests.test_recognition import FakeVision

    asked = []
    monkeypatch.setattr(
        worker_module, "ensure_models", lambda *a, **k: asked.append(k["size"]) or {}
    )
    engine = FakeVision()
    monkeypatch.setattr(worker_module, "PhotoPool", lambda *a: nullcontext(engine))
    win.open_folder(album)
    assert win._size.currentData() == "small"
    assert "MB" in win._size.currentText()
    win._size.setCurrentIndex(win._size.findData("florence-2-base"))
    win._on_recognize()
    assert not win._size.isEnabled() and not win._mode.isEnabled()
    assert win._worker.wait(10000)
    _app.processEvents()
    assert win._size.isEnabled() and win._mode.isEnabled()
    assert asked == ["florence-2-base"]
    stamp = indexer.load(album)["photos"][0]["recognition"]["ocr"]["engine"]
    assert stamp == recognition.engine_id("florence-2-base")
    again = mw.MainWindow()
    assert again._size.currentData() == "florence-2-base"
    again.deleteLater()


def test_the_faces_mode_downloads_face_models_and_matches_by_face(
    win, album, monkeypatch
):
    from contextlib import nullcontext

    from app import recognition_worker as worker_module
    from tests.test_recognition import FakeVision

    asked = []
    monkeypatch.setattr(
        worker_module, "ensure_models", lambda *a, **k: asked.append(k) or {}
    )
    engine = FakeVision()
    monkeypatch.setattr(worker_module, "PhotoPool", lambda *a: nullcontext(engine))
    win.open_folder(album)
    assert "faces" not in win._mode.currentText()
    win._mode.setCurrentIndex(2)
    assert "faces" in win._mode.currentText()
    win._on_recognize()
    assert win._worker.wait(10000)
    _app.processEvents()
    assert asked[0]["faces"] is True and asked[0]["size"] == "small"
    assert ("riders", 0) in engine.calls
    assert "Recognition finished" in win._lbl_status.text()


def test_automatic_errors_are_visible_and_do_not_claim_success(win, album, monkeypatch):
    from app import recognition_worker as worker_module

    warnings = []
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *args: warnings.append(args))

    def broken(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(worker_module, "ensure_models", broken)
    win.open_folder(album)
    before = indexer.load(album)
    win._on_recognize()
    assert win._worker.wait(5000)
    _app.processEvents()
    assert warnings and "offline" in warnings[0][-1]
    assert "failed" in win._lbl_status.text()
    assert win._index == before
    assert win._btn_open.isEnabled()


def test_closing_during_a_model_download_requests_cancel_before_destroying_the_thread(
    win, album, monkeypatch
):
    import threading

    from app import recognition_worker as worker_module
    from app.model_cache import CancelledError

    ready = threading.Event()

    def downloading(appearance, progress, cancel, **kwargs):
        ready.set()
        while not cancel():
            threading.Event().wait(0.005)
        raise CancelledError

    monkeypatch.setattr(worker_module, "ensure_models", downloading)
    win.open_folder(album)
    win._on_recognize()
    thread = win._worker
    assert ready.wait(2)
    win.close()
    assert win._closing and thread.isInterruptionRequested()
    assert thread.wait(5000)
    _app.processEvents()
    assert win._worker is None
    assert "Stopped" in win._lbl_status.text()


def test_a_heic_photo_is_visible_through_its_jpeg_preview(win, tmp_path):
    from PIL import Image

    path = tmp_path / "phone.HEIC"
    Image.new("RGB", (64, 48), "red").save(path, format="HEIF")
    win.open_folder(tmp_path)
    assert win._list.count() == 1
    assert not win._image.pixmap().isNull()


def test_the_button_can_finish_a_real_spawned_photo_pool(win, album, monkeypatch):
    from app import parallel
    from app import recognition_worker as worker_module
    from tests.test_parallel import initialize_fake

    monkeypatch.setattr(parallel, "_initialize", initialize_fake)
    monkeypatch.setattr(worker_module, "ensure_models", lambda *args, **kwargs: {})
    monkeypatch.setattr(worker_module, "plan_for", lambda *args: parallel.Plan(2, 1))
    win.open_folder(album)
    win._on_recognize()
    assert win._worker.wait(10000)
    _app.processEvents()
    assert win._worker is None
    assert "Recognition finished" in win._lbl_status.text()
    assert win._index == indexer.load(album)


def test_a_broken_optional_preview_does_not_hide_a_readable_jpeg(win, album):
    win._chk_previews.setChecked(True)
    win.open_folder(album)
    photo = win._index["photos"][0]
    (album / photo["preview"]["path"]).write_bytes(b"not a preview")
    win._show_photo(0)
    assert not win._image.pixmap().isNull()


def test_a_start_protocol_is_optional_used_and_remembered_for_its_album_only(
    win, album, tmp_path, monkeypatch
):
    from contextlib import nullcontext

    from app import recognition_worker as worker_module
    from tests.conftest import make_photo
    from tests.test_recognition import FakeVision

    monkeypatch.setattr(worker_module, "ensure_models", lambda *a, **k: {})
    engine = FakeVision()
    monkeypatch.setattr(worker_module, "PhotoPool", lambda *a: nullcontext(engine))
    protocol, empty = tmp_path / "start.txt", tmp_path / "empty.txt"
    protocol.write_text("7#Rider#Men#\n", encoding="utf-8")
    empty.write_text("\n", encoding="utf-8")
    chosen = [protocol]
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileName", lambda *a, **k: (str(chosen[0]), "")
    )
    warnings = []
    monkeypatch.setattr(
        mw.QMessageBox, "warning", lambda *args: warnings.append(args[-1])
    )
    win.open_folder(album)
    assert win._btn_protocol.text() == "Start protocol: none"
    assert not win._btn_no_protocol.isEnabled()
    win._on_protocol()
    assert win._btn_protocol.text() == "Start protocol: start.txt"
    assert "1 bibs" in win._lbl_status.text()
    win._on_recognize()
    assert not win._btn_protocol.isEnabled() and not win._btn_no_protocol.isEnabled()
    assert win._worker.wait(10000)
    _app.processEvents()
    red = indexer.load(album)["photos"][0]
    assert [(b["value"], b["state"]) for b in red["bibs"]] == [("012", "rejected")]
    again = mw.MainWindow()  # reopens the last album with its protocol
    assert again._protocol == protocol
    again.deleteLater()
    other = tmp_path / "other"
    other.mkdir()
    make_photo(other, "IMG_0001.jpg")
    win.open_folder(other)
    assert win._protocol is None
    win.open_folder(album)
    assert win._protocol == protocol
    chosen[0] = empty
    win._on_protocol()
    assert win._protocol == protocol and "has no bibs" in warnings[-1]
    win._btn_no_protocol.click()
    assert win._protocol is None and not win._btn_no_protocol.isEnabled()
    win.open_folder(album)
    assert win._protocol is None
