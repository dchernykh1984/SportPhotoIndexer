"""The window: open an album folder, look at each photo, type the bibs on it.

Typing is the whole job, so the keyboard drives it: the bib field keeps focus, Enter
saves the photo's bibs and moves to the next one, and the index is written after every
photo -- nothing is lost if the program is closed halfway through an album.
"""

from __future__ import annotations

import csv
from copy import deepcopy
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QEventLoop, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import indexer, settings
from app.index_format import INDEX_FILE
from app.model_cache import CancelledError, download_megabytes
from app.recognition_worker import RecognitionWorker

_PENDING = "not checked"
_NO_BIB = "no bib"
# Larger models find more bibs and take longer (docs/recognition-benchmark.md).
_SIZES = {
    "small": "Small models",
    "florence-2-base-int8": "Medium: Florence-2 base, 8-bit",
    "florence-2-base": "Large: Florence-2 base",
}


class _ScanWorker(QThread):
    """indexer.scan off the window's thread: hashing a large album takes minutes."""

    progress = Signal(str, int, int)

    def __init__(self, folder: Path, index: dict | None, previews: bool, parent=None):
        super().__init__(parent)
        self.folder, self.index, self.previews = folder, index, previews
        self.result: tuple[dict, indexer.ScanReport] | None = None
        self.error: Exception | None = None

    def run(self) -> None:
        try:
            self.result = indexer.scan(
                self.folder,
                self.index,
                previews=self.previews,
                progress=self._step,
                cancel=self.isInterruptionRequested,
            )
        except Exception as exc:  # raised again on the window's thread
            self.error = exc

    def _step(self, done: int, total: int) -> None:
        self.progress.emit("Checking photos", done, total)


def _upright(path: Path, longest: int) -> QPixmap:
    """The photo as it was taken: cameras store a portrait shot sideways and say so
    in EXIF, which a plain QPixmap ignores. Previews are already upright.

    Decoded straight to at most ``longest`` pixels a side: 50 MP in full is 200 MB of
    pixels, slow to decode, and above 64 MP over Qt's allocation limit."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and max(size.width(), size.height()) > longest:
        reader.setScaledSize(
            size.scaled(longest, longest, Qt.AspectRatioMode.KeepAspectRatio)
        )
    return QPixmap.fromImage(reader.read())


class _Photo(QLabel):
    """The photo, scaled to all the room the window gives it, sharp on Retina."""

    def __init__(self) -> None:
        super().__init__()
        self._original = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 240)
        # Sized by the layout, not by the pixmap, so the window can shrink again.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

    def longest(self) -> int:
        """The longest side worth keeping of a photo, in device pixels: that of the
        sharpest screen, so the window can move to it without the photo blurring."""
        sides = (
            max(s.availableGeometry().width(), s.availableGeometry().height())
            * s.devicePixelRatio()
            for s in QGuiApplication.screens()
        )
        return round(max(sides))

    def show_photo(self, pixmap: QPixmap) -> None:
        # Never more than a screenful: a 50 MP original scaled again on every resize
        # makes dragging the window edge stutter.
        longest = self.longest()
        if max(pixmap.width(), pixmap.height()) > longest:
            pixmap = pixmap.scaled(
                longest,
                longest,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self._original = pixmap
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802 -- Qt virtual method
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        if self._original.isNull():
            self.clear()
            return
        ratio = self.devicePixelRatioF()
        scaled = self._original.scaled(
            self.size() * ratio,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.setPixmap(scaled)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sport Photo Indexer")
        self._folder: Path | None = None
        self._index: dict | None = None
        self._worker: RecognitionWorker | None = None
        self._scanner: _ScanWorker | None = None
        self._protocol: Path | None = None
        self._closing = False
        self._setup_ui()
        # After the window is shown, so a large album scans in view. The window is the
        # timer's context: deleted first, it cancels the call instead of receiving it.
        QTimer.singleShot(0, self, self._reopen_last)

    def _reopen_last(self) -> None:
        last = settings.load().get("folder")
        if last and Path(last).is_dir():
            self.open_folder(Path(last))

    # -- layout --------------------------------------------------------------------

    def _setup_ui(self) -> None:
        self._central = QWidget()
        self.setCentralWidget(self._central)
        root = QVBoxLayout(self._central)

        bar = QHBoxLayout()
        self._btn_open = QPushButton("Open folder...")
        self._btn_open.clicked.connect(self._on_open)
        bar.addWidget(self._btn_open)
        self._btn_rescan = QPushButton("Rescan folder")
        self._btn_rescan.clicked.connect(self.rescan)
        bar.addWidget(self._btn_rescan)
        self._btn_csv = QPushButton("Import bibs (CSV)...")
        self._btn_csv.clicked.connect(self._on_import_csv)
        bar.addWidget(self._btn_csv)
        self._btn_protocol = QPushButton()
        self._btn_protocol.setToolTip(
            "Optional: the race's start protocol (start.txt of StartProtocolMaker, or"
            " a table with the bib first). Read numbers that are not in it are"
            " rejected: banners, car plates, displays."
        )
        self._btn_protocol.clicked.connect(self._on_protocol)
        bar.addWidget(self._btn_protocol)
        self._btn_no_protocol = QPushButton("Clear")
        self._btn_no_protocol.setToolTip("Look for any bib, without a start protocol")
        self._btn_no_protocol.clicked.connect(self._on_no_protocol)
        bar.addWidget(self._btn_no_protocol)
        self._chk_previews = QCheckBox("Make a preview of every photo")
        self._chk_previews.setToolTip(
            "Previews are always made for photos over 20 MB, which Dropbox cannot"
            " shrink; other photos do without."
        )
        bar.addWidget(self._chk_previews)
        bar.addStretch()
        root.addLayout(bar)

        automatic = QHBoxLayout()
        automatic.addWidget(QLabel("Automatic search:"))
        self._mode = QComboBox()
        self._mode.addItems(
            [
                "Bib numbers only",
                "Bib numbers, then rider appearance",
                "Bib numbers, then rider appearance and faces",
            ]
        )
        # The search that finds the most is the default (docs/recognition-benchmark.md).
        self._mode.setCurrentIndex(2)
        automatic.addWidget(self._mode)
        self._size = QComboBox()
        for size, title in _SIZES.items():
            self._size.addItem(f"{title} ({download_megabytes(False, size)} MB)", size)
        saved = self._size.findData(settings.load().get("model_size"))
        self._size.setCurrentIndex(
            saved if saved >= 0 else self._size.findData("florence-2-base")
        )
        self._size.currentIndexChanged.connect(self._on_size)
        automatic.addWidget(self._size)
        self._btn_auto = QPushButton("Recognize automatically")
        self._btn_auto.clicked.connect(self._on_recognize)
        automatic.addWidget(self._btn_auto)
        self._btn_stop = QPushButton("Stop")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)
        automatic.addWidget(self._btn_stop)
        self._progress = QProgressBar()
        self._progress.setRange(0, 1)
        automatic.addWidget(self._progress, 1)
        root.addLayout(automatic)
        help_text = QLabel(
            "Runs on this computer (no photo uploads or recognition fees). "
            "First use downloads the chosen models, "
            f"{download_megabytes(True) - download_megabytes(False)} MB more with"
            " appearance; then works offline. "
            "Bibs: digits and Latin letters. Appearance searches this album only, "
            "using the rider's whole look; the faces mode compares faces too "
            f"({download_megabytes(True, faces=True) - download_megabytes(True)} MB"
            " more). Suggestions need checking. "
            "Put only one event in a folder. Stop keeps saved progress."
        )
        help_text.setWordWrap(True)
        root.addWidget(help_text)

        self._lbl_folder = QLabel("Open the folder of one photographer's album.")
        root.addWidget(self._lbl_folder)

        split = QSplitter(Qt.Orientation.Horizontal)
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._show_photo)
        split.addWidget(self._list)
        right = QWidget()
        side = QVBoxLayout(right)
        self._image = _Photo()
        side.addWidget(self._image, 1)
        side.addWidget(QLabel("Bibs on this photo (separated by spaces):"))
        entry = QHBoxLayout()
        self._edit_bibs = QLineEdit()
        self._edit_bibs.returnPressed.connect(self._on_enter)
        entry.addWidget(self._edit_bibs, 1)
        self._btn_save = QPushButton("Save and next (Enter)")
        self._btn_save.clicked.connect(self._on_enter)
        entry.addWidget(self._btn_save)
        side.addLayout(entry)
        split.addWidget(right)
        split.setSizes([300, 800])
        split.setStretchFactor(0, 0)  # a larger window is for a larger photo
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        self._lbl_status = QLabel()
        root.addWidget(self._lbl_status)
        self._set_enabled(False)

    def _set_enabled(self, on: bool) -> None:
        for widget in (
            self._btn_rescan,
            self._btn_csv,
            self._edit_bibs,
            self._btn_save,
            self._btn_auto,
            self._btn_protocol,
        ):
            widget.setEnabled(on)
        self._show_protocol()

    def _set_running(self, running: bool) -> None:
        # The mode and the model size can be chosen before an album is open.
        for widget in (self._btn_open, self._chk_previews, self._mode, self._size):
            widget.setEnabled(not running)
        self._btn_stop.setEnabled(running)

    def _on_size(self) -> None:
        settings.save({**settings.load(), "model_size": self._size.currentData()})

    def _show_protocol(self) -> None:
        name = self._protocol.name if self._protocol else "none"
        self._btn_protocol.setText(f"Start protocol: {name}")
        self._btn_no_protocol.setEnabled(
            self._btn_protocol.isEnabled() and self._protocol is not None
        )

    def _on_no_protocol(self) -> None:
        self._use_protocol(None)

    def _on_protocol(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self,
            "Start protocol",
            str(self._protocol or self._folder or ""),
            "Start protocol (*.txt *.csv);;All files (*)",
        )
        if chosen:
            self._use_protocol(Path(chosen))

    def _starters(self, path: Path) -> frozenset[str]:
        """The protocol's bibs, or none after telling the user why."""
        try:
            starters = indexer.read_starters(path)
        except OSError as exc:
            QMessageBox.warning(self, "Start protocol", str(exc))
            return frozenset()
        if not starters:
            QMessageBox.warning(
                self,
                "Start protocol",
                f"{path.name} has no bibs: each line should start with one,"
                " as in 12#Name#Category.",
            )
        return starters

    def _protocols(self) -> dict:
        """Each album's start protocol: a protocol belongs to one race."""
        protocols = settings.load().get("start_protocols")
        return dict(protocols) if isinstance(protocols, dict) else {}

    def _use_protocol(self, path: Path | None) -> None:
        if self._folder is None:
            return
        protocols = self._protocols()
        if path is None:
            protocols.pop(str(self._folder), None)
            self._lbl_status.setText("No start protocol: any read bib is suggested")
        else:
            starters = self._starters(path)
            if not starters:
                return
            protocols[str(self._folder)] = str(path)
            # The bibs themselves, so a wrong column (row numbers 1..30) stands out.
            bibs = sorted(starters, key=lambda bib: (len(bib), bib))
            shown = ", ".join(bibs[:3]) + (f" ... {bibs[-1]}" if len(bibs) > 3 else "")
            plural = "s" if len(bibs) > 1 else ""
            self._lbl_status.setText(
                f"Start protocol {path.name}, {len(bibs)} bib{plural}: {shown}"
            )
        self._protocol = path
        settings.save({**settings.load(), "start_protocols": protocols})
        self._show_protocol()

    # -- album ---------------------------------------------------------------------

    def _on_open(self) -> None:
        start = str(self._folder) if self._folder else ""
        chosen = QFileDialog.getExistingDirectory(self, "Album folder", start)
        if chosen:
            self.open_folder(Path(chosen))

    def open_folder(self, folder: Path) -> None:
        try:
            existing = indexer.load(folder)
        except (indexer.IndexError_, OSError) as exc:
            QMessageBox.warning(self, "Open folder", str(exc))
            return
        previous = self._folder, self._index
        self._folder, self._index = folder, existing
        if not self.rescan():
            self._folder, self._index = previous
            return
        settings.save({**settings.load(), "folder": str(folder)})
        # A missing file stays chosen: recognition then stops and says so, instead of
        # quietly running without the protocol.
        remembered = self._protocols().get(str(folder))
        self._protocol = Path(remembered) if remembered else None
        self._show_protocol()

    def rescan(self) -> bool:
        try:
            return self._rescan()
        finally:
            # A close asked for during the scan, once its outcome has been shown.
            if self._closing:
                QTimer.singleShot(0, self, self.close)

    def _rescan(self) -> bool:
        if self._folder is None:
            return False
        try:
            scanned = self._scan(self._folder)
        except (
            indexer.IndexError_,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            QMessageBox.warning(self, "Scan folder", str(exc))
            return False
        if scanned is None:
            return False
        index, report = scanned
        if not self._write(index):
            return False
        self._index = index
        self._lbl_folder.setText(str(self._folder))
        self._fill_list()
        self._set_enabled(bool(index["photos"]))
        notes = [
            f"{report.added} new, {report.changed} changed, {report.removed} gone,"
            f" {report.previews} previews",
            *report.messages,
        ]
        self._lbl_status.setText(self._summary() + " | " + "; ".join(notes))
        self._list.setCurrentRow(self._first_unchecked())
        return True

    def _scan(self, folder: Path) -> tuple[dict, indexer.ScanReport] | None:
        """The folder scanned on a worker thread while the window keeps drawing; None
        when closing the window stopped it."""
        worker = _ScanWorker(folder, self._index, self._chk_previews.isChecked(), self)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.progress.connect(self._show_progress)
        self._scanner = worker
        # Every control off, so the index cannot change meanwhile; the progress bar and
        # the status line stay readable.
        controls = [
            widget
            for kind in (QAbstractButton, QComboBox, QLineEdit, QListWidget)
            for widget in self._central.findChildren(kind)
            if widget.isEnabled()
        ]
        for widget in controls:
            widget.setEnabled(False)
        worker.start()
        loop.exec()
        # The loop also ends when the application quits: never wait out a long scan.
        worker.requestInterruption()
        worker.wait()
        self._scanner = None
        for widget in controls:
            widget.setEnabled(True)
        worker.deleteLater()
        if worker.error is not None:  # no count of a check that did not finish
            self._progress.setRange(0, 1)
            self._progress.setValue(0)
        if isinstance(worker.error, CancelledError):
            self._lbl_status.setText("Folder check stopped")
            return None
        if worker.error is not None:
            self._lbl_status.setText(f"Folder check failed: {worker.error}")
            raise worker.error
        return worker.result

    def _on_import_csv(self) -> None:
        if self._index is None or self._folder is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Bibs table", str(self._folder), "CSV (*.csv *.txt)"
        )
        if not path:
            return
        candidate = deepcopy(self._index)
        try:
            applied, unknown = indexer.import_csv(candidate, Path(path))
        except (indexer.IndexError_, OSError, csv.Error) as exc:
            QMessageBox.warning(self, "Import bibs", str(exc))
            return
        if not self._write(candidate):
            return
        self._index = candidate
        self._fill_list()
        missing = f"; not in the folder: {', '.join(unknown[:5])}" if unknown else ""
        QMessageBox.information(self, "Import bibs", f"{applied} photo(s) set{missing}")

    # -- photos ----------------------------------------------------------------------

    def _label(self, photo: dict) -> str:
        name = photo["original"]["path"]
        if photo["processing_state"] != "processed":
            return f"{name}  -  {_PENDING}"
        candidates = [b["value"] for b in photo["bibs"] if b["state"] == "candidate"]
        label = f"{name}  -  {', '.join(indexer.bibs_of(photo)) or _NO_BIB}"
        return label + (
            f"  | check: {', '.join(dict.fromkeys(candidates))}" if candidates else ""
        )

    def _fill_list(self) -> None:
        row = self._list.currentRow()
        self._list.blockSignals(True)
        self._list.clear()
        for photo in (self._index or {}).get("photos", []):
            item = QListWidgetItem(self._label(photo))
            item.setData(Qt.ItemDataRole.UserRole, photo["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if 0 <= row < self._list.count():
            self._list.setCurrentRow(row)

    def _first_unchecked(self) -> int:
        photos = (self._index or {}).get("photos", [])
        for row, photo in enumerate(photos):
            if photo["processing_state"] != "processed":
                return row
        return 0 if photos else -1

    def _photo(self, row: int) -> dict | None:
        if self._index is None or not 0 <= row < len(self._index["photos"]):
            return None
        return self._index["photos"][row]

    def _show_photo(self, row: int) -> None:
        photo = self._photo(row)
        if photo is None or self._folder is None:
            self._image.show_photo(QPixmap())
            return
        asset = photo.get("preview", photo["original"])
        longest = self._image.longest()
        pixmap = _upright(self._folder / asset["path"], longest)
        if pixmap.isNull() and asset is not photo["original"]:
            pixmap = _upright(self._folder / photo["original"]["path"], longest)
        self._image.show_photo(pixmap)
        self._edit_bibs.setText(" ".join(indexer.bibs_of(photo)))
        self._edit_bibs.selectAll()
        self._edit_bibs.setFocus()

    def _on_enter(self) -> None:
        row = self._list.currentRow()
        photo = self._photo(row)
        if photo is None or self._index is None:
            return
        try:
            bibs = indexer.parse_bibs(self._edit_bibs.text())
        except indexer.IndexError_ as exc:
            self._lbl_status.setText(str(exc))
            return
        candidate = deepcopy(self._index)
        indexer.set_bibs(candidate, photo["id"], bibs)
        if not self._write(candidate):
            return
        self._index = candidate
        self._list.item(row).setText(self._label(candidate["photos"][row]))
        self._lbl_status.setText(self._summary())
        if row + 1 < self._list.count():
            self._list.setCurrentRow(row + 1)

    def _write(self, candidate: dict | None = None) -> bool:
        candidate = self._index if candidate is None else candidate
        if self._folder is None or candidate is None:
            return False
        try:
            indexer.save(self._folder, candidate)
        except (indexer.IndexError_, OSError) as exc:
            QMessageBox.warning(self, f"Saving {INDEX_FILE}", str(exc))
            return False
        return True

    def _summary(self) -> str:
        photos = (self._index or {}).get("photos", [])
        checked = sum(p["processing_state"] == "processed" for p in photos)
        with_bibs = sum(bool(indexer.bibs_of(p)) for p in photos)
        return f"{len(photos)} photos, {checked} checked, {with_bibs} with bibs"

    def _on_recognize(self) -> None:
        if self._worker is not None or self._index is None or self._folder is None:
            return
        starters = self._starters(self._protocol) if self._protocol else frozenset()
        if self._protocol and not starters:
            return
        self._set_enabled(False)
        self._set_running(True)
        self._worker = RecognitionWorker(
            self._folder,
            self._index,
            appearance=self._mode.currentIndex() >= 1,
            size=self._size.currentData(),
            faces=self._mode.currentIndex() == 2,
            starters=starters,
            parent=self,
        )
        self._worker.progress.connect(self._show_progress)
        self._worker.finished.connect(self._recognition_finished)
        self._lbl_status.setText("Preparing local models...")
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._btn_stop.setEnabled(False)
            self._lbl_status.setText("Stopping after the current operation...")

    def _show_progress(self, phase: str, done: int, total: int) -> None:
        working = (w for w in (self._worker, self._scanner) if w is not None)
        if any(w.isInterruptionRequested() for w in working):
            return  # the "Stopping..." line stays until the work has ended
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(done)
        self._lbl_status.setText(f"{phase}: {done} / {total}")

    def _recognition_finished(self) -> None:
        worker = self._worker
        if worker is None:
            return
        try:
            self._index = indexer.load(worker.folder)
        except (indexer.IndexError_, OSError) as exc:
            worker.error = f"{worker.error}; {exc}".strip("; ")
        self._worker = None
        self._fill_list()
        self._show_photo(self._list.currentRow())
        self._set_enabled(bool((self._index or {}).get("photos")))
        self._set_running(False)
        if worker.error:
            state = "Recognition failed; saved progress kept"
        elif worker.report.cancelled:
            state = "Stopped; saved progress kept"
        elif worker.report.errors:
            state = "Recognition finished with errors"
        else:
            state = "Recognition finished"
        self._lbl_status.setText(
            f"{state}. {self._summary()}. Rider references: {worker.report.seeds}."
        )
        if worker.error or worker.report.errors:
            QMessageBox.warning(
                self,
                "Automatic recognition",
                "\n".join([worker.error, *worker.report.errors[:5]]).strip(),
            )
        worker.deleteLater()
        if self._closing:
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802 -- Qt virtual method
        if self._scanner is not None:
            self._closing = True
            self._scanner.requestInterruption()
            self._lbl_status.setText("Stopping the folder check...")
            event.ignore()
        elif self._worker is not None and self._worker.isRunning():
            self._closing = True
            self._on_stop()
            event.ignore()
        else:
            super().closeEvent(event)
