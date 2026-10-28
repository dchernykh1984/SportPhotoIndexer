"""Check that every recognition model still downloads from each of its sources.

    uv run python -m tools.models [DIR]

Downloads each model from every source the app knows (app.model_cache.sources: the
catalog's sources, then this repository's mirror release) into DIR, data/models by
default, which git ignores. Run there, it keeps the verified copy the mirror is filled
from; the weekly `models` workflow runs it to learn that a source has lost a model
before the app's users do. Exits 1 when a model has a failing source and the mirror
does not hold that model yet, and prints the commands that upload it there.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

from app.model_cache import CATALOG, MIRROR, download, sources

RELEASE = MIRROR.rstrip("/").rsplit("/", 1)[1]


def _fetch(key: str, url: str, path: Path) -> Exception | None:
    """One source, once more after a failure: a connection dropped in a weekly run
    must not read as a lost model."""
    error: Exception | None = None
    for _ in range(2):
        try:
            download(key, url, path, lambda *a: None, lambda: False)
            return None
        except Exception as exc:  # every source is reported, whatever went wrong
            error = exc
    return error


def check(folder: Path) -> list[str]:
    """Report every source; the file names of the models the mirror must get."""
    folder.mkdir(parents=True, exist_ok=True)
    missing = []
    for key, model in CATALOG.items():
        name = Path(model["path"]).name
        failed = mirrored = False
        for url in sources(key):
            ours = url.startswith(MIRROR)
            error = _fetch(key, url, folder / name)
            if error is None:
                print(f"ok     {url}")
                mirrored |= ours
                continue
            empty = isinstance(error, urllib.error.HTTPError) and error.code == 404
            print(f"{'empty ' if ours and empty else 'FAILED'} {url}: {error}")
            failed |= not (ours and empty)
        if failed and not mirrored:
            missing.append(name)
    return missing


def main(folder: Path) -> int:
    missing = check(folder)
    if not missing:
        return 0
    print(
        "\nA source has lost these models and the mirror does not hold them yet."
        "\nUpload them from data/models of a checkout where this check passed before:"
        f"\n  gh release view {RELEASE} >/dev/null || gh release create {RELEASE}"
        " --latest=false --title 'Recognition models'"
        " --notes 'Copies of models whose sources failed; see MODEL_NOTICES.md.'"
    )
    for name in missing:
        print(f"  gh release upload {RELEASE} --clobber data/models/{name}")
    return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/models")))
