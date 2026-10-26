"""Qt's background worker owns its index copy; the window never edits it mid-run."""

from copy import deepcopy

from PySide6.QtCore import QThread, Signal

from app import recognition
from app.model_cache import CancelledError, ensure_models
from app.vision import CpuVision


class RecognitionWorker(QThread):
    progress = Signal(str, int, int)

    def __init__(self, folder, index, *, appearance: bool, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.index = deepcopy(index)
        self.appearance = appearance
        self.report = recognition.Report()
        self.error = ""

    def run(self):
        try:
            models = ensure_models(
                self.appearance, self.progress.emit, self.isInterruptionRequested
            )
            engine = CpuVision(models)
            self.report = recognition.run(
                self.folder,
                self.index,
                engine,
                appearance=self.appearance,
                progress=self.progress.emit,
                cancel=self.isInterruptionRequested,
            )
        except CancelledError:
            self.report.cancelled = True
        except (
            Exception
        ) as exc:  # the Qt thread must report failures, never kill the app
            self.error = str(exc)
