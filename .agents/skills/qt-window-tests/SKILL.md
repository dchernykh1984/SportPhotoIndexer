---
name: qt-window-tests
description: How to test the PySide6 main window in this repository -- the offscreen setup, the fixture that keeps a test off the real disk and out of dialogs, testing timer-driven and dialog-driven handlers, and rendering the window to a PNG to check a layout. Use when changing or testing anything in app/main_window.py.
---

# Testing the window

`app/main_window.py` is excluded from coverage, so these tests are the only thing
standing between a handler and a silent regression. Add one for every handler change.

## Setup

The platform plugin must be selected before `QtWidgets` is imported, and the
`QApplication` is a module-level singleton:

```python
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from app import main_window as mw

_app = QApplication.instance() or QApplication([])
```

## The fixture

`MainWindow.__init__` reopens the last album from `data/spi_settings.json`. Stub
`app.settings.load`/`save` in the fixture (see `tests/test_window.py`), monkeypatch
`QMessageBox.information`/`warning`, and give each test its own album folder from the
`album` fixture in `tests/conftest.py` -- the index is written into it.

## Timers

Do not wait for a `QTimer` to fire. Call the slot directly and assert on
`timer.isActive()`. For that to mean the same thing as a real firing, the slot should
stop its own timer on entry -- a single-shot timer stops itself when Qt fires it, but
not when a test calls the slot.

```python
win._save_all_data()
assert win._auto_send_timer.isActive() is True  # queued, not sent
win._on_auto_send_timeout()
assert len(uploads.calls) == 1
```

Debounce is testable this way too: several edits followed by one timeout must produce
exactly one upload.

## Simulating the user

`setText` does not emit `textEdited`, so a handler that distinguishes typed input from
values it wrote itself will not see it. Type instead:

```python
from PySide6.QtTest import QTest

edit.clear()
QTest.keyClicks(edit, "30")
```

## Asserting that no dialog appears

Replace the dialog with a raiser rather than a no-op, and the test fails if the code
ever tries to open one:

```python
monkeypatch.setattr(mw.QMessageBox, "warning", _fail)
```

## Checking a layout

The offscreen platform still renders, so a layout change can be verified as an image
instead of by eye:

```python
w.resize(1400, 900)
w.show()
app.processEvents()
w.grab().save("/tmp/window.png")
```

Useful for stretch factors and row ordering. Keep it as a scratch script, not a test.
