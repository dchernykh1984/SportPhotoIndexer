"""Turn the labelling log into the files that index the album.

    uv run python -m tools.album.labels WORKDIR

WORKDIR/labels.txt has one line per photo, `n|visible|identified|note`:
- visible: bibs readable on that photo (at full resolution), space-separated;
- identified: starters recognised there without a readable bib; `12?` marks a
  probable one and `@red-jacket` a person not identified yet (a tag to resolve
  later); both are reported but not written to the index;
- note: how it was decided.
Lines starting with `#` are comments.

Writes WORKDIR/bibs.csv (`file;bibs`, visible and identified, for
`app.cli index --csv`) and WORKDIR/review.csv (photos with identified, probable or
unlabelled people, for the person who checks the work).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path


def read(work: Path) -> tuple[dict[int, str], list[list[str]]]:
    with (work / "photos.csv").open(encoding="utf-8") as fh:
        names = {int(row[0]): row[1] for row in csv.reader(fh)}
    rows = []
    for line in (work / "labels.txt").read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("|")
        if len(fields) != 4 or not fields[0].isdigit() or int(fields[0]) not in names:
            raise ValueError(f"bad label line: {line!r}")
        rows.append(fields)
    seen = [int(r[0]) for r in rows]
    if missing := sorted(set(names) - set(seen)):
        raise ValueError(f"photos without a label line: {missing[:20]}")
    if len(seen) != len(set(seen)):
        raise ValueError("a photo is labelled twice")
    return names, rows


def main(work: Path) -> int:
    names, rows = read(work)
    pairs = probable = 0
    with (
        (work / "bibs.csv").open("w", newline="", encoding="utf-8") as bibs,
        (work / "review.csv").open("w", newline="", encoding="utf-8") as review,
    ):
        index = csv.writer(bibs, delimiter=";")
        check = csv.writer(review, delimiter=";")
        index.writerow(["file", "bibs"])
        check.writerow(["file", "visible", "identified", "probable", "unknown", "note"])
        for n, visible, identified, note in rows:
            tokens = identified.split()
            unknown = [t for t in tokens if t.startswith("@")]
            maybe = [t[:-1] for t in tokens if t.endswith("?") and t not in unknown]
            sure = [t for t in tokens if t not in unknown and not t.endswith("?")]
            bibs_on_photo = list(dict.fromkeys(visible.split() + sure))
            index.writerow([names[int(n)], " ".join(bibs_on_photo)])
            pairs += len(bibs_on_photo)
            probable += len(maybe)
            if identified.strip() or note.strip():
                name = names[int(n)]
                check.writerow(
                    [
                        name,
                        visible,
                        *(" ".join(t) for t in (sure, maybe, unknown)),
                        note,
                    ]
                )
    print(f"{len(rows)} photos, {pairs} photo-bib pairs to index, {probable} probable")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
