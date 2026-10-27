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
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
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
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import indexer, settings
from app.index_format import INDEX_FILE
from app.model_cache import download_megabytes
from app.recognition_worker import RecognitionWorker

_PENDING = "not checked"
_NO_BIB = "no bib"
# Larger models find more bibs and take longer (docs/recognition-benchmark.md).
_SIZES = {
    "small": "Small models",
    "florence-2-base": "Medium: Florence-2 base",
    "florence-2-large": "Large: Florence-2 large",
}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sport Photo Indexer")
        self._folder: Path | None = None
        self._index: dict | None = None
        self._worker: RecognitionWorker | None = None
        self._closing = False
        self._setup_ui()
        last = settings.load().get("folder")
        if last and Path(last).is_dir():
            self.open_folder(Path(last))

    # -- layout --------------------------------------------------------------------

    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

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
        self._mode.addItems(["Bib numbers only", "Bib numbers, then rider appearance"])
        self._mode.setCurrentIndex(1)
        automatic.addWidget(self._mode)
        self._size = QComboBox()
        for size, title in _SIZES.items():
            self._size.addItem(f"{title} ({download_megabytes(False, size)} MB)", size)
        self._size.setCurrentIndex(
            max(0, self._size.findData(settings.load().get("model_size")))
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
            "using the "
            "rider's whole look, without face recognition. Suggestions need checking. "
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
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setMinimumSize(320, 240)
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
            self._mode,
            self._size,
        ):
            widget.setEnabled(on)

    def _on_size(self) -> None:
        settings.save({**settings.load(), "model_size": self._size.currentData()})

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

    def rescan(self) -> bool:
        if self._folder is None:
            return False
        try:
            index, report = indexer.scan(
                self._folder, self._index, previews=self._chk_previews.isChecked()
            )
        except (
            indexer.IndexError_,
            OSError,
            ValueError,
            Image.DecompressionBombError,
        ) as exc:
            QMessageBox.warning(self, "Scan folder", str(exc))
            return False
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
            self._image.clear()
            return
        asset = photo.get("preview", photo["original"])
        pixmap = QPixmap(str(self._folder / asset["path"]))
        if pixmap.isNull() and asset is not photo["original"]:
            pixmap = QPixmap(str(self._folder / photo["original"]["path"]))
        self._image.setPixmap(
            pixmap.scaled(
                self._image.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
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
        self._set_enabled(False)
        self._btn_open.setEnabled(False)
        self._chk_previews.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._worker = RecognitionWorker(
            self._folder,
            self._index,
            appearance=self._mode.currentIndex() == 1,
            size=self._size.currentData(),
            parent=self,
        )
        self._worker.progress.connect(self._recognition_progress)
        self._worker.finished.connect(self._recognition_finished)
        self._lbl_status.setText("Preparing local models...")
        self._worker.start()

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.requestInterruption()
            self._btn_stop.setEnabled(False)
            self._lbl_status.setText("Stopping after the current operation...")

    def _recognition_progress(self, phase: str, done: int, total: int) -> None:
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
        self._btn_open.setEnabled(True)
        self._chk_previews.setEnabled(True)
        self._btn_stop.setEnabled(False)
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
        if self._worker is not None and self._worker.isRunning():
            self._closing = True
            self._on_stop()
            event.ignore()
        else:
            super().closeEvent(event)
