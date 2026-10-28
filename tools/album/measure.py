"""Measure the app's recognition on a labelled album without touching the album.

    uv run python -m tools.album.measure ALBUM WORKDIR COPYDIR [MODELS] [SIZE] [faces]
        [PROTOCOL]

COPYDIR gets symbolic links to the album's photos, then the app's own scan and
recognition (appearance included) run there, exactly as the window runs them. The
index is scored against WORKDIR/labels.txt (see tools.album.labels): how many
visible bibs and how many people without a readable bib it found, how many values
belong to nobody on the photo -- also counting those that are some starter's bib
(only those reach a participant's album on the site). Run it on the main branch and
on a change to compare. COPYDIR keeps its index, so a second run reuses saved OCR
read with the same model SIZE (small by default; see app.model_cache.SIZES).
An argument "faces" matches riders by face as well as by body; a PROTOCOL file
(see app.indexer.read_starters) rejects read bibs that are not in it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from app import indexer, recognition
from app.model_cache import download_megabytes, ensure_models
from app.parallel import PhotoPool, plan_for
from tools.album.labels import read


def run(
    album: Path,
    copy: Path,
    models: Path,
    size: str = "small",
    faces: bool = False,
    starters: frozenset[str] = frozenset(),
) -> dict:
    copy.mkdir(parents=True, exist_ok=True)
    for photo in indexer.photo_files(album):
        if not (copy / photo.name).exists():
            (copy / photo.name).symlink_to(photo.resolve())
    index, _ = indexer.scan(copy, indexer.load(copy))
    indexer.save(copy, index)
    paths = ensure_models(True, lambda *a: None, lambda: False, models, size, faces)
    megabytes = download_megabytes(True, size, faces)
    plan = plan_for(len(index["photos"]), megabytes * 1_000_000)
    started = time.time()
    with PhotoPool(paths, plan) as engine:
        report = recognition.run(
            copy,
            index,
            engine,
            appearance=True,
            progress=lambda *a: None,
            cancel=lambda: False,
            size=size,
            faces=faces,
            starters=starters,
        )
    print(f"recognition took {time.time() - started:.0f} s, {report}")
    return index


def score(work: Path, index: dict) -> None:
    names, rows = read(work)
    visible, identified = set(), set()
    for n, seen, known, _ in rows:
        visible |= {(names[int(n)], b) for b in seen.split()}
        identified |= {
            (names[int(n)], b.rstrip("?")) for b in known.split() if b[0] != "@"
        }
    everyone = visible | identified
    starters = {b for _, b in everyone}
    for level in ("accepted", "candidate"):
        found = {
            (p["original"]["path"], b["value"])
            for p in index["photos"]
            for b in p["bibs"]
            if b["state"] in ("accepted", level)
        }
        wrong = found - everyone
        print(
            f"{'accepted' if level == 'accepted' else 'with candidates':16s}"
            f" visible {len(found & visible)}/{len(visible)}"
            f" ({len(found & visible) / max(1, len(visible)):.1%})"
            f" | without a bib {len(found & identified - visible)}/{len(identified)}"
            f" | wrong {len(wrong)}/{len(found)}"
            f" ({len(wrong) / max(1, len(found)):.1%}),"
            f" of them starters' bibs {sum(b in starters for _, b in wrong)}"
        )


if __name__ == "__main__":
    album, work, copy = map(Path, sys.argv[1:4])
    models = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("data/models")
    size = sys.argv[5] if len(sys.argv) > 5 else "small"
    rest = sys.argv[6:]
    protocols = [Path(a) for a in rest if a != "faces"]
    if len(protocols) > 1:
        sys.exit(f"one PROTOCOL at most, not {[str(p) for p in protocols]}")
    starters = indexer.read_starters(protocols[0]) if protocols else frozenset()
    if protocols and not starters:
        sys.exit(f"{protocols[0]} has no bibs: it would be measured as no protocol")
    score(work, run(album, copy, models, size, "faces" in rest, starters))
