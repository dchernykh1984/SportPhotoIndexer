"""Qt's background worker owns its index copy; the window never edits it mid-run."""

from copy import deepcopy

from PySide6.QtCore import QThread, Signal

from app import recognition
from app.model_cache import CancelledError, ensure_models
from app.parallel import PhotoPool, plan_for


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
            plan = plan_for(len(self.index["photos"]))
            self.progress.emit(f"Preparing {plan.workers} parallel photo workers", 0, 1)
            with PhotoPool(models, plan) as engine:
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
