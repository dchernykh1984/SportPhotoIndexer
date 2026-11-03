"""What the program remembers between runs, in a file next to it (see app.paths)."""

from __future__ import annotations

import json

from app.paths import app_path

_FILE = ("data", "spi_settings.json")


def load() -> dict:
    try:
        data = json.loads(app_path(*_FILE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def save(values: dict) -> None:
    """Kept when it can be: a program where it may not write forgets its settings
    instead of failing what was asked (opening a folder, ticking a box)."""
    path = app_path(*_FILE)
    text = json.dumps(values, ensure_ascii=False, indent=2)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        return
