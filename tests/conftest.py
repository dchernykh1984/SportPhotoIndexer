from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image


def make_photo(folder: Path, name: str, color: str = "orange", size=(64, 48)) -> Path:
    path = folder / name
    Image.new("RGB", size, color).save(path)
    return path


@pytest.fixture
def album(tmp_path: Path) -> Path:
    folder = tmp_path / "album"
    folder.mkdir()
    for n, color in enumerate(["red", "green", "blue"], 1):
        make_photo(folder, f"IMG_{n:04d}.jpg", color)
    return folder
