"""Viewing copies and a photo table for indexing an album by eye.

    uv run python -m tools.album.prepare ALBUM WORKDIR

Writes WORKDIR/view/NNN.jpg (oriented, long side 1400 px) and WORKDIR/photos.csv:
n, file, width, height, time taken (EXIF), camera. Photos are the ones the indexer
lists, in its order, so n is the same row number everywhere. Originals are only read.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from PIL import Image, ImageOps

from app.indexer import check_decoder, photo_files


def exif_time_and_camera(image: Image.Image) -> tuple[str, str]:
    exif = image.getexif()
    taken = exif.get_ifd(0x8769).get(36867) or exif.get(306) or ""
    return str(taken), str(exif.get(272) or "")


def main(album: Path, work: Path) -> int:
    view = work / "view"
    view.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, path in enumerate(photo_files(album), 1):
        check_decoder(path)
        with Image.open(path) as source:
            taken, camera = exif_time_and_camera(source)
            image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        image.thumbnail((1400, 1400))
        image.save(view / f"{n:03d}.jpg", quality=85)
        rows.append([n, path.name, width, height, taken, camera])
    with (work / "photos.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    print(f"{len(rows)} photos -> {view}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
