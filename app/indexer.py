"""Making and keeping a folder's photo-index.v1.json.

A folder is an album: its photos sit at its root (Dropbox opens a root file directly
from the site), the index sits next to them. Scanning keeps each photo's id between
runs, so the site keeps its marks; a photo that disappeared is listed in
``removed_photo_ids`` rather than silently dropped. Bibs typed by a person are
``manual`` and bound to the bytes they were typed for: if the photo file changes, they
no longer apply and are dropped.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import AvifImagePlugin, Image, ImageOps
from pillow_heif import register_heif_opener

from app import version
from app.index_format import (
    BIB_NORMALIZATION,
    INDEX_FILE,
    MAX_INDEX_BYTES,
    MEDIA_TYPES,
    PREVIEW_MEDIA_TYPES,
    SCHEMA_VERSION,
    THUMBNAIL_LIMIT_BYTES,
    bib_problem,
    normalize_bib,
    photo_problems,
    problems,
)

PREVIEW_DIR = "_previews"
PREVIEW_SIDE = 1024
_CHUNK = 1024 * 1024
register_heif_opener(decode_threads=1, thumbnails=False)
AvifImagePlugin.DEFAULT_MAX_THREADS = 1


class IndexError_(ValueError):  # noqa: N801,N818 -- not the builtin IndexError
    pass


@dataclass
class ScanReport:
    added: int = 0
    removed: int = 0
    changed: int = 0
    stale_bibs: int = 0
    previews: int = 0
    messages: list[str] = field(default_factory=list)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def photo_files(folder: Path) -> list[Path]:
    """An album's photos: image files at its root, by name, hidden ones left out."""
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file()
        and not p.name.startswith(".")
        and p.suffix.lower() in MEDIA_TYPES
    )


def load(folder: Path, *, validate: bool = True) -> dict | None:
    path = folder / INDEX_FILE
    if not path.exists():
        return None
    try:
        with path.open("rb") as fh:
            raw = fh.read(MAX_INDEX_BYTES + 1)
        if len(raw) > MAX_INDEX_BYTES:
            raise IndexError_(f"{INDEX_FILE} exceeds {MAX_INDEX_BYTES} bytes")
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise IndexError_(f"{INDEX_FILE} cannot be read: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("photos"), list):
        raise IndexError_(f"{INDEX_FILE} is not a photo index")
    if validate and (found := problems(data)):
        raise IndexError_("; ".join(found[:5]))
    return data


def new_index() -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "album_id": str(uuid.uuid4()),
        "revision": 0,
        "generated_at": "",
        "producer": {"name": "SportPhotoIndexer", "version": version()},
        "bib_normalization": BIB_NORMALIZATION,
        "processing": {
            "inventory_complete": False,
            "complete": False,
            "total": 0,
            "processed": 0,
        },
        "photos": [],
        "removed_photo_ids": [],
    }


def _asset(folder: Path, path: Path, sha: str) -> dict:
    return {
        "path": path.relative_to(folder).as_posix(),
        "sha256": sha,
        "bytes": path.stat().st_size,
        "media_type": MEDIA_TYPES[path.suffix.lower()],
    }


def check_decoder(path: Path) -> None:
    if path.suffix.lower() == ".avif" and not AvifImagePlugin.SUPPORTED:
        raise OSError(
            "AVIF decoding is unavailable in this build (including Windows ARM64). "
            "Use JPEG, PNG, WebP or HEIC/HEIF, or index this album on another platform."
        )


def _make_preview(folder: Path, original: Path) -> Path:
    check_decoder(original)
    # The full name, so same.jpg and same.png do not share one preview.
    target = folder / PREVIEW_DIR / f"{original.name}.jpg"
    target.parent.mkdir(exist_ok=True)
    with Image.open(original) as source:
        img = ImageOps.exif_transpose(source).convert("RGB")
        img.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
        img.save(target, "JPEG", quality=82, optimize=True)  # no EXIF: none is copied
    return target


def scan(
    folder: Path,
    index: dict | None = None,
    *,
    previews: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> tuple[dict, ScanReport]:
    """The folder's index brought up to date with the files in it.

    ``previews`` makes a preview for every photo; one is always made for an original
    Dropbox cannot thumbnail (over 20 MB).
    """
    index = json.loads(json.dumps(index)) if index else new_index()
    report = ScanReport()
    by_path = {p["original"]["path"]: p for p in index["photos"]}
    # Photos that left the folder, kept so the same file coming back gets its old id.
    gone_before = _removed_records(index)
    files = photo_files(folder)
    photos = []
    for n, path in enumerate(files, 1):
        if progress:
            progress(n, len(files))
        sha = sha256_of(path)
        rel = path.name
        photo = by_path.pop(rel, None)
        changed = False
        if photo is None:
            photo = _returned_photo(gone_before.pop((rel, sha), None))
            report.added += 1
        elif photo["original"]["sha256"] != sha:
            changed = True
            report.changed += 1
            kept = [b for b in photo["bibs"] if b.get("method") != "manual"]
            report.stale_bibs += len(photo["bibs"]) - len(kept)
            _archive_review(photo)
            photo["bibs"] = []
            photo.pop("manual_review", None)
            photo.pop("recognition", None)
            photo.pop("recognition_error", None)
            photo["processing_state"] = "pending"
        photo["original"] = _asset(folder, path, sha)
        # A preview made from the old file would show the old picture: remake it.
        if (
            previews
            or (
                MEDIA_TYPES[path.suffix.lower()] not in PREVIEW_MEDIA_TYPES
                and "preview" not in photo
            )
            or (
                "preview" in photo
                and (
                    not (folder / photo["preview"]["path"]).is_file()
                    or sha256_of(folder / photo["preview"]["path"])
                    != photo["preview"]["sha256"]
                )
            )
            or (changed and "preview" in photo)
            or path.stat().st_size > THUMBNAIL_LIMIT_BYTES
        ):
            preview = _make_preview(folder, path)
            photo["preview"] = _asset(folder, preview, sha256_of(preview))
            report.previews += 1
        photos.append(photo)
    gone = list(by_path.values())
    report.removed = len(gone)
    back = {p["id"] for p in photos}
    index["photos"] = photos
    index["removed_photo_ids"] = sorted(
        ({*index.get("removed_photo_ids", []), *(p["id"] for p in gone)}) - back
    )
    index["removed_photos"] = list(gone_before.values()) + [
        {
            "id": p["id"],
            "path": p["original"]["path"],
            "sha256": p["original"]["sha256"],
            "photo": deepcopy(p),
        }
        for p in gone
    ]
    index["processing"]["inventory_complete"] = True
    update_counts(index)
    if report.stale_bibs:
        report.messages.append(
            f"{report.stale_bibs} typed bib(s) dropped: their photo file changed"
        )
    return index, report


def _removed_records(index):
    records = index.get("removed_photos", [])
    if not isinstance(records, list):
        raise IndexError_("removed_photos must be a list of saved photos")
    result = {}
    for record in records:
        if not isinstance(record, dict) or not all(
            isinstance(record.get(key), str) for key in ("path", "sha256", "id")
        ):
            raise IndexError_("removed_photos contains an invalid saved photo")
        try:
            uuid.UUID(record["id"])
        except ValueError as exc:
            raise IndexError_("removed_photos contains an invalid photo ID") from exc
        result[(record["path"], record["sha256"])] = record
    return result


def _returned_photo(record):
    if record is not None and "photo" in record:
        photo = record["photo"]
        found = photo_problems(photo, "saved photo")
        if found:
            raise IndexError_("; ".join(found[:5]))
        if (photo["id"], photo["original"]["path"], photo["original"]["sha256"]) != (
            record["id"],
            record["path"],
            record["sha256"],
        ):
            raise IndexError_("saved photo does not match its original bytes and ID")
        return deepcopy(photo)
    # Legacy indexes kept only the ID, not the reviewed annotations.
    return {
        "id": record["id"] if record else str(uuid.uuid4()),
        "processing_state": "pending",
        "bibs": [],
    }


def update_counts(index: dict) -> None:
    processed = sum(p["processing_state"] == "processed" for p in index["photos"])
    proc = index["processing"]
    proc.update(total=len(index["photos"]), processed=processed)
    proc["complete"] = proc["inventory_complete"] and processed == proc["total"]


def parse_bibs(text: str) -> list[str]:
    """Bibs typed by a person: separated by spaces, commas or semicolons."""
    tokens = [
        normalize_bib(t) for t in text.replace(",", " ").replace(";", " ").split()
    ]
    for token in tokens:
        if why := bib_problem(token):
            raise IndexError_(f"{token!r}: {why}")
    return list(dict.fromkeys(tokens))


def set_bibs(index: dict, photo_id: str, bibs: list[str]) -> None:
    """A person looked at the photo: these bibs are on it (maybe none)."""
    photo = next(p for p in index["photos"] if p["id"] == photo_id)
    sha = photo["original"]["sha256"]
    typed = set(bibs)
    # What the person typed is accepted; a bib found before that they left out is
    # rejected by them, so a later automatic pass cannot bring it back. A read the
    # start protocol rejected was never shown to them, so they did not judge it.
    dropped = {
        b["value"]
        for b in photo["bibs"]
        if b["value"] not in typed
        and not (b["method"] == "ocr" and b["state"] == "rejected")
    }
    regions = {b["value"]: b["region"] for b in photo["bibs"] if "region" in b}
    previous = photo.get("manual_review")
    if previous and set(bibs_of(photo)) != typed:
        _archive_review(photo)
    photo["manual_review"] = {
        "original_sha256": sha,
        "lock_accepted_set": True,
        "review_id": previous["review_id"]
        if previous and set(bibs_of(photo)) == typed
        else str(uuid.uuid4()),
    }
    photo["bibs"] = [
        {
            "value": b,
            "state": "accepted",
            "method": "manual",
            "content_sha256": sha,
            **({"region": regions[b]} if b in regions else {}),
        }
        for b in bibs
    ] + [
        {"value": b, "state": "rejected", "method": "manual", "content_sha256": sha}
        for b in sorted(dropped)
    ]
    photo["processing_state"] = "processed"
    update_counts(index)


def _archive_review(photo: dict) -> None:
    if photo.get("manual_review") or any(
        b["method"] == "manual" for b in photo["bibs"]
    ):
        photo.setdefault("manual_history", []).append(
            {
                "review": deepcopy(photo.get("manual_review")),
                "bibs": deepcopy([b for b in photo["bibs"] if b["method"] == "manual"]),
            }
        )


def bibs_of(photo: dict) -> list[str]:
    return [b["value"] for b in photo["bibs"] if b["state"] == "accepted"]


def import_csv(index: dict, path: Path) -> tuple[int, list[str]]:
    """Bibs from a ``file;bibs`` table: (photos set, file names not in the album)."""
    by_name = {p["original"]["path"]: p for p in index["photos"]}
    applied, unknown = 0, []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        dialect = (
            csv.Sniffer().sniff(sample, delimiters=";,\t") if sample else csv.excel
        )
        for row in csv.reader(fh, dialect):
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            if name not in by_name:
                if name.lower() not in ("file", "filename", "photo"):
                    unknown.append(name)
                continue
            set_bibs(index, by_name[name]["id"], parse_bibs(" ".join(row[1:])))
            applied += 1
    return applied, unknown


def read_starters(path: Path) -> frozenset[str]:
    """Bibs of a start protocol: the first field of each line, as in the ``start.txt``
    of StartProtocolMaker (``12#Name#Category#...``) or a table with the bib first.
    A field without a digit (a header, a name, an unpaid marker) is no bib: a reader
    never reports one, so it would only make a wrong file look right."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    first = (re.split("[#;,\t]", line, maxsplit=1)[0] for line in text.splitlines())
    bibs = (normalize_bib(field.strip().strip("\"'")) for field in first)
    return frozenset(
        b for b in bibs if not bib_problem(b) and any(c.isdigit() for c in b)
    )


def _content(index: dict) -> dict:
    return {k: v for k, v in index.items() if k not in ("revision", "generated_at")}


class StaleIndexError(IndexError_):
    pass


def save(folder: Path, index: dict) -> bool:
    """Write the index next to the photos; False when nothing changed since last time.

    The revision moves only when the content does, and the file is replaced in one
    step, so the site never reads half of it. ``index`` must be based on the revision
    now on disk: an index opened before somebody else saved is refused rather than
    allowed to overwrite their work. A lock file keeps two programs from writing at
    once.
    """
    with _lock(folder):
        previous = load(folder)
        on_disk = (previous or {}).get("revision", 0)
        if on_disk != index.get("revision", 0):
            raise StaleIndexError(
                f"{INDEX_FILE} was changed elsewhere (revision {on_disk});"
                " reopen the folder"
            )
        if previous is not None and _content(previous) == _content(index):
            return False
        candidate = {
            **index,
            "revision": on_disk + 1,
            "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        found = problems(candidate)
        if found:
            raise IndexError_("; ".join(found[:5]))
        data = json.dumps(candidate, ensure_ascii=False, separators=(",", ":")).encode()
        if len(data) > MAX_INDEX_BYTES:
            raise IndexError_(
                f"the index would be {len(data)} bytes, over the site's limit of "
                f"{MAX_INDEX_BYTES}; split the album into two folders"
            )
        _replace(folder, data)
        index.update(
            revision=candidate["revision"], generated_at=candidate["generated_at"]
        )
    return True


def _replace(folder: Path, data: bytes) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".photo-index-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        Path(tmp).replace(folder / INDEX_FILE)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


_LOCK_FILE = ".photo-index.lock"
_STALE_LOCK_SECONDS = 60


@contextmanager
def _lock(folder: Path) -> Iterator[None]:
    path = folder / _LOCK_FILE
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        age = time.time() - path.stat().st_mtime
        if age < _STALE_LOCK_SECONDS:
            raise StaleIndexError(
                "another program is writing this album's index"
            ) from None
        path.unlink(missing_ok=True)  # left by a program that crashed
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
