"""The window: open an album folder, look at each photo, type the bibs on it.

Typing is the whole job, so the keyboard drives it: the bib field keeps focus, Enter
saves the photo's bibs and moves to the next one, and the index is written after every
photo -- nothing is lost if the program is closed halfway through an album.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import indexer, settings
from app.index_format import INDEX_FILE

_PENDING = "not checked"
_NO_BIB = "no bib"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sport Photo Indexer")
        self._folder: Path | None = None
        self._index: dict | None = None
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
        ):
            widget.setEnabled(on)

    # -- album ---------------------------------------------------------------------

    def _on_open(self) -> None:
        start = str(self._folder) if self._folder else ""
        chosen = QFileDialog.getExistingDirectory(self, "Album folder", start)
        if chosen:
            self.open_folder(Path(chosen))

    def open_folder(self, folder: Path) -> None:
        try:
            existing = indexer.load(folder)
        except indexer.IndexError_ as exc:
            QMessageBox.warning(self, "Open folder", str(exc))
            return
        self._folder = folder
        self._index = existing
        settings.save({**settings.load(), "folder": str(folder)})
        self.rescan()

    def rescan(self) -> None:
        if self._folder is None:
            return
        index, report = indexer.scan(
            self._folder, self._index, previews=self._chk_previews.isChecked()
        )
        self._index = index
        self._write()
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

    def _on_import_csv(self) -> None:
        if self._index is None or self._folder is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Bibs table", str(self._folder), "CSV (*.csv *.txt)"
        )
        if not path:
            return
        try:
            applied, unknown = indexer.import_csv(self._index, Path(path))
        except indexer.IndexError_ as exc:
            QMessageBox.warning(self, "Import bibs", str(exc))
            return
        self._write()
        self._fill_list()
        missing = f"; not in the folder: {', '.join(unknown[:5])}" if unknown else ""
        QMessageBox.information(self, "Import bibs", f"{applied} photo(s) set{missing}")

    # -- photos ----------------------------------------------------------------------

    def _label(self, photo: dict) -> str:
        name = photo["original"]["path"]
        if photo["processing_state"] != "processed":
            return f"{name}  -  {_PENDING}"
        return f"{name}  -  {', '.join(indexer.bibs_of(photo)) or _NO_BIB}"

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
        indexer.set_bibs(self._index, photo["id"], bibs)
        if not self._write():
            return
        self._list.item(row).setText(self._label(photo))
        self._lbl_status.setText(self._summary())
        if row + 1 < self._list.count():
            self._list.setCurrentRow(row + 1)

    def _write(self) -> bool:
        if self._folder is None or self._index is None:
            return False
        try:
            indexer.save(self._folder, self._index)
        except (indexer.IndexError_, OSError) as exc:
            QMessageBox.warning(self, f"Saving {INDEX_FILE}", str(exc))
            return False
        return True

    def _summary(self) -> str:
        photos = (self._index or {}).get("photos", [])
        checked = sum(p["processing_state"] == "processed" for p in photos)
        with_bibs = sum(bool(indexer.bibs_of(p)) for p in photos)
        return f"{len(photos)} photos, {checked} checked, {with_bibs} with bibs"
