"""Check that every recognition model still downloads from each of its sources.

    uv run python -m tools.models [DIR]

Downloads each model from every source the app knows (app.model_cache.sources: the
catalog's sources, then this repository's mirror release) into DIR, data/models by
default, which git ignores. Run there, it keeps the verified copy the mirror is filled
from; the weekly `models` workflow runs it to learn that a source has lost a model
before the app's users do. Exits 1 when a source fails, or the mirror cannot be read
or holds other bytes under a model's name, and prints what to do: the commands that
upload the models the mirror lacks, and the dead sources to remove from the catalog.
"""

from __future__ import annotations

import dataclasses
import shlex
import sys
import time
import urllib.error
from collections.abc import Callable
from pathlib import Path

from app.model_cache import (
    CATALOG,
    MIRROR,
    SOURCE_ERRORS,
    CancelledError,
    CutShortError,
    ModelError,
    download_from,
    file_name,
    sources,
    verified,
)

RELEASE = MIRROR.rstrip("/").rsplit("/", 1)[1]
# Tries of a source whose failure may pass, half a minute apart: ModelScope stalls for
# longer than a read timeout now and then on the far side of the world.
ATTEMPTS = 3
PAUSE = 30
# The longest one source may take for one file. The largest model, 388 MB, comes from
# ModelScope to the runners in about 4 minutes; a source sending a trickle must not
# hold the run until the job's time limit cuts it off before its summary.
SLOWEST = 20 * 60


def _lasting(error: Exception) -> bool:
    """A failure another try would repeat: the source sent other bytes, or answered
    that it does not have the file. A download cut short may pass."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code in (404, 410)  # a 429 or 408 from a busy host may pass
    return isinstance(error, ModelError) and not isinstance(error, CutShortError)


def _past(deadline: float) -> Callable[[], bool]:
    return lambda: time.monotonic() > deadline


def _fetch(key: str, url: str, path: Path) -> Exception | None:
    """One source, again after a failure that may pass: a connection dropped in a
    weekly run must not read as a lost model."""
    error: Exception | None = None
    for attempt in range(ATTEMPTS):
        if attempt:
            time.sleep(PAUSE)
        too_slow = _past(time.monotonic() + SLOWEST)
        try:
            download_from(key, url, path, lambda *a: None, too_slow)
            return None
        except CancelledError:  # too slow; another try would take as long
            return TimeoutError(f"slower than {SLOWEST // 60} minutes for one file")
        except SOURCE_ERRORS as exc:  # a disk error stops the check, as it does the app
            error = exc
            if _lasting(exc):
                break
    return error


@dataclasses.dataclass
class Report:
    """What the check found to do; empty when every source gave its model."""

    upload: list[Path] = dataclasses.field(default_factory=list)  # verified here
    lost: list[str] = dataclasses.field(default_factory=list)  # no verified copy here
    dead: list[str] = dataclasses.field(default_factory=list)  # catalog sources
    unread: list[str] = dataclasses.field(default_factory=list)  # mirror files
    clashes: list[str] = dataclasses.field(default_factory=list)  # mirror files

    def __bool__(self) -> bool:
        return any((self.upload, self.lost, self.dead, self.unread, self.clashes))


def check(folder: Path) -> Report:
    """Report every source, and what to do about the models whose sources failed."""
    folder.mkdir(parents=True, exist_ok=True)
    report = Report()
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
            # What to do is said at once, so a run cut off by its time limit says it.
            if not ours:
                failed = True
                report.dead.append(url)
                print(
                    f"-> remove from app/model_catalog.json once it stays down: {url}"
                )
            elif isinstance(error, ModelError) and not isinstance(error, CutShortError):
                # Other bytes under this name may be the ones an older app pins.
                report.clashes.append(url)
                unknown = True
                print(f"-> the mirror holds other bytes under {name}")
            elif not empty:
                # Neither empty nor other bytes: whether it holds the model is unknown.
                report.unread.append(url)
                unknown = True
        if failed and not mirrored and not unknown:
            if verified(key, folder / name):
                report.upload.append(folder / name)
                print(f"-> upload: {_upload(folder / name)}")
            else:
                report.lost.append(name)
                print(f"-> no verified copy of {name} here to upload")
    return report


def _upload(path: Path) -> str:
    # No --clobber: a file already in the release under this name is never replaced.
    return f"gh release upload {RELEASE} {shlex.quote(str(path))}"


def main(folder: Path) -> int:
    report = check(folder)
    create = (
        f"gh release view {RELEASE} >/dev/null || gh release create {RELEASE}"
        " --latest=false --title 'Recognition models'"
        " --notes 'Copies of models whose sources failed; see MODEL_NOTICES.md.'"
    )
    sections = [
        (
            "A source has lost these models and the mirror does not hold them yet."
            " Upload them from this folder:",
            [create, *map(_upload, report.upload)] if report.upload else [],
        ),
        (
            "No source gave these models and no verified copy of them is here. Upload"
            " each from the data/models of a checkout where this check passed before;"
            " if none holds it, the model is lost:",
            report.lost,
        ),
        (
            # The app tries a dead source before the mirror on every fresh download.
            "These sources failed. Once one stays down, remove it from"
            " app/model_catalog.json, or the app keeps trying it first:",
            report.dead,
        ),
        (
            "The mirror could not be read; look at it before uploading anything:",
            report.unread,
        ),
        (
            "The mirror holds other bytes under these names than the catalog pins. An"
            " installed app may still need them: give the new version of the model a"
            " new file name in app/model_catalog.json instead of replacing them:",
            report.clashes,
        ),
    ]
    for title, lines in sections:
        if lines:
            print(f"\n{title}")
            for line in lines:
                print(f"  {line}")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else "data/models")))
