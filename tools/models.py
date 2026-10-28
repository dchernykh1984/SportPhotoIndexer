"""Check that every recognition model still downloads from each of its sources.

    uv run python -m tools.models [DIR]

Downloads each model from every source the app knows (app.model_cache.sources: the
catalog's sources, then this repository's mirror release) into DIR, data/models by
default, which git ignores. Run there, it keeps the verified copy the mirror is filled
from; the weekly `models` workflow runs it to learn that a source has lost a model
before the app's users do. Exits 1 when a source fails on every try or the mirror
cannot be read, and prints what to do: the commands that upload the models the mirror
lacks, and the dead sources to remove from the catalog.
"""

from __future__ import annotations

import shlex
import sys
import time
import urllib.error
from pathlib import Path

from app.model_cache import (
    CATALOG,
    MIRROR,
    SOURCE_ERRORS,
    CutShortError,
    ModelError,
    download_from,
    file_name,
    sources,
)

RELEASE = MIRROR.rstrip("/").rsplit("/", 1)[1]
# Tries of a source whose failure may pass, half a minute apart: ModelScope stalls for
# longer than a read timeout now and then on the far side of the world.
ATTEMPTS = 3
PAUSE = 30


def _lasting(error: Exception) -> bool:
    """A failure another try would repeat: the source sent other bytes, or answered
    that it does not have the file. A download cut short may pass."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (404, 410)  # a 429 or 408 from a busy host may pass
    return isinstance(error, ModelError) and not isinstance(error, CutShortError)


def _fetch(key: str, url: str, path: Path) -> Exception | None:
    """One source, again after a failure that may pass: a connection dropped in a
    weekly run must not read as a lost model."""
    error: Exception | None = None
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(PAUSE)
        try:
            download_from(key, url, path, lambda *a: None, lambda: False)
            return None
        except SOURCE_ERRORS as exc:  # a disk error stops the check, as it does the app
            error = exc
            if _lasting(exc):
                break
    return error


def check(folder: Path) -> tuple[list[str], list[str], list[str]]:
    """Report every source; the file names of the models the mirror must get, the
    catalog's sources that failed, and the mirror's files that could not be read."""
    folder.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    dead: list[str] = []
    unread: list[str] = []
    for key in CATALOG:
        name = file_name(key)
        failed = mirrored = unknown = False
        for url in sources(key):
            ours = url.startswith(MIRROR)
            error = _fetch(key, url, folder / name)
            if error is None:
                print(f"ok     {url}")
                mirrored |= ours
                continue
            empty = isinstance(error, urllib.error.HTTPError) and error.code == 404
            print(f"{'empty ' if ours and empty else 'FAILED'} {url}: {error}")
            if ours and not empty and not isinstance(error, ModelError):
                # Neither empty nor a wrong file: whether it holds the model is unknown.
                unread.append(url)
                unknown = True
                continue
            failed |= not (ours and empty)
            if not ours:
                dead.append(url)
        if failed and not mirrored and not unknown:
            missing.append(name)
    return missing, dead, unread


def main(folder: Path) -> int:
    missing, dead, unread = check(folder)
    if missing:
        print(
            "\nA source has lost these models and the mirror does not hold them yet."
            "\nUpload them from a folder where this check passed before:"
            f"\n  gh release view {RELEASE} >/dev/null || gh release create {RELEASE}"
            " --latest=false --title 'Recognition models'"
            " --notes 'Copies of models whose sources failed; see MODEL_NOTICES.md.'"
        )
        for name in missing:
            file = shlex.quote(str(folder / name))
            print(f"  gh release upload {RELEASE} --clobber {file}")
    if dead:
        # The app tries a dead source before the mirror on every fresh download.
        print(
            "\nThese sources failed on every try. Once one stays down, remove it from"
            " app/model_catalog.json, or the app keeps trying it first:"
        )
        for url in dead:
            print(f"  {url}")
    if unread:
        print("\nThe mirror could not be read; look at it before uploading anything:")
        for url in unread:
            print(f"  {url}")
    return 1 if missing or dead or unread else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/models")))
