"""The window drives the whole manual job: open a folder, type bibs, Enter, next."""

from __future__ import annotations

import os
from pathlib import Path

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
    _app.processEvents()  # its reopen of the last album runs here, not in a later test
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
    _app.processEvents()  # the last album opens once the window is up
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
    _app.processEvents()
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
    assert not win._btn_stop.isEnabled()
    win._mode.setCurrentIndex(1 if appearance else 0)
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
    # Out of the box the search that finds the most: Large models, faces too.
    assert win._mode.currentText() == "Bib numbers, then rider appearance and faces"
    assert win._size.currentData() == "florence-2-base"
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
    assert "MB" in win._size.currentText()
    win._size.setCurrentIndex(win._size.findData("small"))
    win._on_recognize()
    assert not win._size.isEnabled() and not win._mode.isEnabled()
    assert win._worker.wait(10000)
    _app.processEvents()
    assert win._size.isEnabled() and win._mode.isEnabled()
    assert asked == ["small"]
    stamp = indexer.load(album)["photos"][0]["recognition"]["ocr"]["engine"]
    assert stamp == recognition.engine_id("small")
    again = mw.MainWindow()
    _app.processEvents()
    assert again._size.currentData() == "small"
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
    win._mode.setCurrentIndex(2)
    assert "faces" in win._mode.currentText()
    win._on_recognize()
    assert win._worker.wait(10000)
    _app.processEvents()
    assert asked[0]["faces"] is True and asked[0]["size"] == "florence-2-base"
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
    assert win._lbl_status.text() == "Start protocol start.txt, 1 bib: 7"
    win._on_recognize()
    assert not win._btn_protocol.isEnabled() and not win._btn_no_protocol.isEnabled()
    assert win._worker.wait(10000)
    _app.processEvents()
    red = indexer.load(album)["photos"][0]
    assert [(b["value"], b["state"]) for b in red["bibs"]] == [("012", "rejected")]
    again = mw.MainWindow()  # reopens the last album with its protocol
    _app.processEvents()
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
    assert win._lbl_status.text().startswith("No start protocol")
    win.open_folder(album)
    assert win._protocol is None


def test_a_protocol_that_cannot_be_read_stops_recognition_instead_of_dropping_out(
    win, album, tmp_path, monkeypatch
):
    protocol = tmp_path / "start.txt"
    protocol.write_text("7#Rider#Men#\n", encoding="utf-8")
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileName", lambda *a, **k: (str(protocol), "")
    )
    warnings = []
    monkeypatch.setattr(
        mw.QMessageBox, "warning", lambda *args: warnings.append(args[-1])
    )
    win.open_folder(album)
    win._on_protocol()
    protocol.write_text("\n", encoding="utf-8")  # emptied after it was chosen
    win._on_recognize()
    assert win._worker is None and "has no bibs" in warnings[-1]
    protocol.unlink()  # the drive with the protocol is gone
    win.open_folder(album)
    assert win._btn_protocol.text() == "Start protocol: start.txt"
    win._on_recognize()
    assert win._worker is None and "start.txt" in warnings[-1]
    assert win._btn_auto.isEnabled() and win._btn_no_protocol.isEnabled()


def test_the_bibs_a_protocol_gave_are_shown_so_a_wrong_column_is_noticed(
    win, album, tmp_path, monkeypatch
):
    table = tmp_path / "start.csv"
    rows = [f"{n};{100 + n};Rider {n}" for n in range(1, 31)]
    table.write_text("No;Bib;Name\n" + "\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(
        mw.QFileDialog, "getOpenFileName", lambda *a, **k: (str(table), "")
    )
    win.open_folder(album)
    win._on_protocol()
    assert win._lbl_status.text() == "Start protocol start.csv, 30 bibs: 1, 2, 3 ... 30"


def test_no_signal_is_connected_to_a_lambda_or_a_partial():
    # PySide frees such a receiver before the widgets when Python exits, and the
    # widget's destructor then touches it: the packaged app crashed on close. main()
    # now destroys the window first; this keeps the receivers out as well.
    import re

    for module in Path(mw.__file__).parent.glob("*.py"):
        source = module.read_text(encoding="utf-8")
        assert not re.search(r"connect\(\s*(lambda|partial)\b", source), module.name


def test_an_album_is_scanned_off_the_window_thread_with_progress(
    win, album, monkeypatch
):
    import threading

    on_window_thread = []
    real = indexer.scan

    def scan(*args, **kwargs):
        on_window_thread.append(threading.current_thread() is threading.main_thread())
        return real(*args, **kwargs)

    monkeypatch.setattr(indexer, "scan", scan)
    win.open_folder(album)
    assert on_window_thread == [False] and win._list.count() == 3
    assert win._progress.value() == win._progress.maximum() == 3
    assert win._central.isEnabled()


def test_closing_the_window_stops_a_scan_and_keeps_the_open_album(
    win, album, tmp_path, monkeypatch
):
    import time

    from PySide6.QtCore import QTimer

    from app.model_cache import check_cancel
    from tests.conftest import make_photo

    win.open_folder(album)

    def endless(folder, index=None, *, previews=False, progress=None, cancel=None):
        for _ in range(1000):
            check_cancel(cancel)  # raises once the window asks the scan to stop
            progress(1, 2)
            time.sleep(0.01)
        raise AssertionError("the scan was never stopped")

    monkeypatch.setattr(indexer, "scan", endless)
    other = tmp_path / "other"
    other.mkdir()
    make_photo(other, "IMG_0001.jpg")
    said = []

    def close():
        win.close()
        win._show_progress("Checking photos", 1, 2)  # a count already queued
        said.append(win._lbl_status.text())

    QTimer.singleShot(50, close)
    win.open_folder(other)
    assert win._folder == album and win._closing
    assert said == ["Stopping the folder check..."]
    assert win._lbl_status.text() == "Folder check stopped"
    assert win._progress.value() == 0


def test_a_larger_window_shows_a_larger_photo_and_keeps_the_list_width(win, album):
    win.open_folder(album)
    win.resize(900, 700)
    win.show()
    _app.processEvents()
    photo, listed = win._image.pixmap().width(), win._list.width()
    win.resize(1800, 1300)
    _app.processEvents()
    assert win._image.pixmap().width() > 1.5 * photo
    assert win._list.width() == listed
    win.resize(900, 700)  # and back: the photo must not hold the window wide
    _app.processEvents()
    assert win._image.pixmap().width() == photo


def test_a_photo_stored_sideways_is_shown_upright(win, album):
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 8  # a portrait shot, stored sideways as cameras do
    Image.new("RGB", (64, 48), "orange").save(album / "IMG_0001.jpg", exif=exif)
    win.open_folder(album)
    win.resize(900, 700)
    win.show()
    _app.processEvents()
    assert win._list.currentRow() == 0
    pixmap = win._image.pixmap()
    assert pixmap.height() > pixmap.width()


def test_a_scan_wait_cut_short_stops_the_scan_instead_of_freezing(
    win, album, tmp_path, monkeypatch
):
    import time

    from app.model_cache import check_cancel
    from tests.conftest import make_photo

    win.open_folder(album)

    def endless(folder, index=None, *, previews=False, progress=None, cancel=None):
        for _ in range(500):
            check_cancel(cancel)
            time.sleep(0.01)
        raise AssertionError("the scan was never stopped")

    from PySide6.QtCore import QObject

    # A nested loop that QApplication.quit() ended at once. A QObject, because a
    # signal connected to a plain Python object crashes PySide when it is torn down.
    class CutShort(QObject):
        def exec(self):
            return 0

        def quit(self):
            pass

    monkeypatch.setattr(indexer, "scan", endless)
    monkeypatch.setattr(mw, "QEventLoop", CutShort)
    other = tmp_path / "other"
    other.mkdir()
    make_photo(other, "IMG_0001.jpg")
    started = time.monotonic()
    win.open_folder(other)
    assert time.monotonic() - started < 2 and win._folder == album


def test_a_close_during_a_failing_scan_waits_for_its_warning(
    win, album, tmp_path, monkeypatch
):
    import time

    from PySide6.QtCore import QTimer

    from tests.conftest import make_photo

    win.open_folder(album)
    win.show()

    def failing(folder, index=None, *, previews=False, progress=None, cancel=None):
        for _ in range(500):
            if cancel():
                break
            time.sleep(0.01)
        raise OSError("the drive went away")  # fails rather than stopping

    shown_under_warning = []

    def warning(*args):
        _app.processEvents()  # what the dialog's own event loop would run
        shown_under_warning.append(win.isVisible())

    monkeypatch.setattr(indexer, "scan", failing)
    monkeypatch.setattr(mw.QMessageBox, "warning", warning)
    other = tmp_path / "other"
    other.mkdir()
    make_photo(other, "IMG_0001.jpg")
    QTimer.singleShot(50, win.close)
    win.open_folder(other)
    assert shown_under_warning == [True]
    assert win._lbl_status.text() == "Folder check failed: the drive went away"
    _app.processEvents()
    assert not win.isVisible()  # closed once the warning was dealt with


def test_a_huge_photo_is_kept_at_screen_size_so_resizing_stays_quick(win):
    from PySide6.QtGui import QPixmap

    huge = QPixmap(9000, 6000)
    huge.fill()
    win._image.show_photo(huge)
    screen = win._image.screen().availableGeometry().size()
    screen *= win._image.devicePixelRatioF()
    kept = win._image._original
    assert kept.width() <= screen.width() and kept.height() <= screen.height()


def test_the_window_is_destroyed_before_python_exits(monkeypatch):
    # Left to interpreter exit, PySide frees signal receivers before the widgets and
    # a widget's destructor can touch a freed one: 0.5.0 crashed on close that way.
    import PySide6.QtWidgets
    import shiboken6

    from app import main as entry

    class App:  # the test's QApplication stands in; exec returns as if closed
        def __init__(self, argv):
            pass

        def __getattr__(self, name):
            return lambda *args: 0

    windows = []

    class Window(mw.MainWindow):
        def __init__(self):
            super().__init__()
            windows.append(self)

    monkeypatch.setattr(settings, "load", lambda: {})
    monkeypatch.setattr(settings, "save", lambda values: None)
    monkeypatch.setattr(PySide6.QtWidgets, "QApplication", App)
    monkeypatch.setattr(mw, "MainWindow", Window)
    monkeypatch.setattr(entry.sys, "argv", ["SportPhotoIndexer"])
    with pytest.raises(SystemExit):
        entry.main()
    assert len(windows) == 1 and not shiboken6.isValid(windows[0])


def test_a_deleted_window_never_runs_its_pending_reopen(monkeypatch):
    import shiboken6

    asked = []
    monkeypatch.setattr(settings, "load", lambda: asked.append(1) or {})
    monkeypatch.setattr(settings, "save", lambda values: None)
    w = mw.MainWindow()
    before = len(asked)
    shiboken6.delete(w)
    _app.processEvents()
    assert len(asked) == before


def test_a_running_worker_thread_is_stopped_before_the_window_is_destroyed(
    monkeypatch,
):
    # Deleting a running QThread aborts the process, so an exit that skipped the
    # window's close (a session logoff) must still end the work first.
    import PySide6.QtWidgets
    import shiboken6
    from PySide6.QtCore import QThread

    from app import main as entry

    class App:
        def __init__(self, argv):
            pass

        def __getattr__(self, name):
            return lambda *args: 0

    class Spin(QThread):
        def run(self):
            while not self.isInterruptionRequested():
                self.msleep(5)

    windows = []

    class Window(mw.MainWindow):
        def __init__(self):
            super().__init__()
            self.spin = Spin(self)
            self.spin.start()
            windows.append(self)

    monkeypatch.setattr(settings, "load", lambda: {})
    monkeypatch.setattr(settings, "save", lambda values: None)
    monkeypatch.setattr(PySide6.QtWidgets, "QApplication", App)
    monkeypatch.setattr(mw, "MainWindow", Window)
    monkeypatch.setattr(entry.sys, "argv", ["SportPhotoIndexer"])
    with pytest.raises(SystemExit):
        entry.main()
    assert not shiboken6.isValid(windows[0])


def test_a_large_photo_is_decoded_straight_to_screen_size_and_upright(tmp_path):
    from PIL import Image

    exif = Image.Exif()
    exif[0x0112] = 8
    path = tmp_path / "large.jpg"
    Image.new("RGB", (4000, 3000), "orange").save(path, exif=exif)
    pixmap = mw._upright(path, 800)
    assert (pixmap.width(), pixmap.height()) == (600, 800)


def test_a_photo_is_kept_sharp_enough_for_the_sharpest_screen(win, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import QRect

    def screen(width, height, ratio):
        return SimpleNamespace(
            availableGeometry=lambda: QRect(0, 0, width, height),
            devicePixelRatio=lambda: ratio,
        )

    laptop, studio = screen(1920, 1080, 1.0), screen(2560, 1440, 2.0)
    monkeypatch.setattr(mw.QGuiApplication, "screens", lambda: [laptop, studio])
    assert win._image.longest() == 5120  # moved to the 5K display, still sharp


def test_the_scan_progress_stays_readable_while_the_controls_are_off(win, album):
    during = []
    show = win._show_progress

    def record(phase, done, total):
        show(phase, done, total)
        states = (win._progress, win._lbl_status, win._btn_open, win._list)
        during.append(tuple(w.isEnabled() for w in states))

    win._show_progress = record  # connected when the scan starts
    win.open_folder(album)
    assert during and set(during) == {(True, True, False, False)}
    assert win._btn_open.isEnabled() and win._list.isEnabled()
