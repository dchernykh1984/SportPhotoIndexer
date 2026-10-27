"""Full-resolution crops of several photos side by side, to read small bibs.

    uv run python -m tools.album.look ALBUM WORKDIR OUT.jpg N:x0,y0,x1,y1 ... [HEIGHT]

N is the row in WORKDIR/photos.csv; the box is in fractions of the oriented photo
(0,0,1,1 is the whole frame). Each crop is scaled to HEIGHT pixels (default 300,
enlarged at most three times) and labelled with N.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def crops(album: Path, work: Path, specs: list[str], height: int) -> list[Image.Image]:
    with (work / "photos.csv").open(encoding="utf-8") as fh:
        names = {int(row[0]): row[1] for row in csv.reader(fh)}
    tiles = []
    for spec in specs:
        n, box = spec.split(":")
        x0, y0, x1, y1 = map(float, box.split(","))
        with Image.open(album / names[int(n)]) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        w, h = image.size
        tile = image.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
        scale = min(height / tile.height, 3.0)
        tile = tile.resize(
            (max(1, int(tile.width * scale)), max(1, int(tile.height * scale)))
        )
        ImageDraw.Draw(tile).text((4, 4), n, fill=(255, 0, 0))
        tiles.append(tile)
    return tiles


def montage(tiles: list[Image.Image], width: int = 1400) -> Image.Image:
    rows: list[list[Image.Image]] = [[]]
    used = 0
    for tile in tiles:
        if rows[-1] and used + tile.width > width:
            rows.append([])
            used = 0
        rows[-1].append(tile)
        used += tile.width + 6
    out = Image.new(
        "RGB",
        (
            max(sum(t.width + 6 for t in row) for row in rows),
            sum(max(t.height for t in row) + 6 for row in rows),
        ),
        "white",
    )
    y = 0
    for row in rows:
        x = 0
        for tile in row:
            out.paste(tile, (x, y))
            x += tile.width + 6
        y += max(t.height for t in row) + 6
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    height = int(args.pop()) if args[-1].isdigit() else 300
    album, work, out, specs = Path(args[0]), Path(args[1]), Path(args[2]), args[3:]
    montage(crops(album, work, specs, height)).save(out, quality=90)
    print(out)
