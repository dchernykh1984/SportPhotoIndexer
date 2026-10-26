"""The photo-index.v1.json format, and the same checks the site applies to it.

The contract lives in cycling-site, ``specs/349-external-photo-albums/contracts/
photo-index.md``. ``problems`` returns what the site would refuse, field by field, so
the indexer never writes an index the site cannot import.
"""

from __future__ import annotations

import re
import unicodedata
import uuid

INDEX_FILE = "photo-index.v1.json"
SCHEMA_VERSION = 1
BIB_NORMALIZATION = "trim-nfc-exact-v1"
MEDIA_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}
# Dropbox makes no thumbnail of a file bigger than this; such a photo needs a preview.
THUMBNAIL_LIMIT_BYTES = 20 * 1024 * 1024
# The site's defaults (PHOTO_INDEX_MAX_*); an album over them is refused on import.
MAX_PHOTOS = 5000
MAX_INDEX_BYTES = 5_000_000
MAX_BIBS_PER_PHOTO = 20
MAX_BIB_LENGTH = 32
MAX_PATH = 500

_SHA = re.compile(r"^[0-9a-f]{64}\Z")
_STATES = {"candidate", "accepted", "rejected"}
_METHODS = {"ocr", "appearance", "manual"}
_PROCESSING = {"pending", "processed", "failed"}


def normalize_bib(value: str) -> str:
    """``trim-nfc-exact-v1``: trim and NFC; leading zeroes, letters and case stay."""
    return unicodedata.normalize("NFC", value.strip())


def bib_problem(value: str) -> str:
    """Why a typed bib cannot go into the index, or "" when it can."""
    bib = normalize_bib(value)
    if not 1 <= len(bib) <= MAX_BIB_LENGTH:
        return f"a bib is 1 to {MAX_BIB_LENGTH} characters"
    if any(unicodedata.category(c).startswith("C") or c in " ,;" for c in bib):
        return "a bib has no spaces, commas or control characters"
    return ""


def path_problem(path: object) -> str:
    if not isinstance(path, str) or not path or len(path) > MAX_PATH:
        return "missing or too long"
    if path.startswith("/") or "://" in path or "\\" in path:
        return "not a safe relative path"
    if any(ord(c) < 32 or c == "\x7f" for c in path):
        return "not a safe relative path"
    if any(part in ("", ".", "..") for part in path.split("/")):
        return "not a safe relative path"
    return ""


def _asset_problems(asset: object, where: str) -> list[str]:
    if not isinstance(asset, dict):
        return [f"{where}: missing"]
    found = []
    if why := path_problem(asset.get("path")):
        found.append(f"{where}.path: {why}")
    if not isinstance(asset.get("sha256"), str) or not _SHA.match(asset["sha256"]):
        found.append(f"{where}.sha256: must be the file's SHA-256")
    size = asset.get("bytes")
    if not isinstance(size, int) or isinstance(size, bool) or size < 1:
        found.append(f"{where}.bytes: must be a positive integer")
    if asset.get("media_type") not in set(MEDIA_TYPES.values()):
        found.append(f"{where}.media_type: must be JPEG, PNG or WebP")
    return found


def _bib_problems(bib: object, where: str, original_sha: object) -> list[str]:
    if not isinstance(bib, dict) or not isinstance(bib.get("value"), str):
        return [f"{where}: not a bib"]
    found = []
    if why := bib_problem(bib["value"]):
        found.append(f"{where}.value: {why}")
    if bib.get("state") not in _STATES:
        found.append(f"{where}.state: must be candidate, accepted or rejected")
    if bib.get("method") not in _METHODS:
        found.append(f"{where}.method: must be ocr, appearance or manual")
    if bib.get("method") == "manual" and bib.get("content_sha256") != original_sha:
        found.append(f"{where}.content_sha256: must be the original's SHA-256")
    if bib.get("method") == "appearance" and bib.get("state") != "candidate":
        found.append(f"{where}.state: an appearance match is always a candidate")
    return found


def _photo_problems(photo: object, where: str) -> list[str]:
    if not isinstance(photo, dict):
        return [f"{where}: not a photo"]
    found = []
    try:
        uuid.UUID(str(photo.get("id")))
    except ValueError:
        found.append(f"{where}.id: not a UUID")
    found += _asset_problems(photo.get("original"), f"{where}.original")
    if photo.get("preview") is not None:
        found += _asset_problems(photo["preview"], f"{where}.preview")
    if photo.get("processing_state") not in _PROCESSING:
        found.append(f"{where}.processing_state: must be pending, processed or failed")
    bibs = photo.get("bibs", [])
    if not isinstance(bibs, list) or len(bibs) > MAX_BIBS_PER_PHOTO:
        return [*found, f"{where}.bibs: at most {MAX_BIBS_PER_PHOTO}"]
    original_sha = (photo.get("original") or {}).get("sha256")
    for j, bib in enumerate(bibs):
        found += _bib_problems(bib, f"{where}.bibs[{j}]", original_sha)
    return found


def problems(index: dict) -> list[str]:
    """Everything the site would refuse in this index; empty when it is fine."""
    found = []
    if index.get("schema_version") != SCHEMA_VERSION:
        found.append(f"schema_version: must be {SCHEMA_VERSION}")
    if index.get("bib_normalization") != BIB_NORMALIZATION:
        found.append(f"bib_normalization: must be {BIB_NORMALIZATION}")
    revision = index.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        found.append("revision: must be a positive integer")
    photos = index.get("photos")
    if not isinstance(photos, list):
        return [*found, "photos: must be a list"]
    if len(photos) > MAX_PHOTOS:
        found.append(f"photos: more than {MAX_PHOTOS}")
    for i, photo in enumerate(photos):
        found += _photo_problems(photo, f"photos[{i}]")
    ids = [p.get("id") for p in photos if isinstance(p, dict)]
    if len(set(ids)) != len(ids):
        found.append("photos: a photo id repeats")
    removed = set(index.get("removed_photo_ids", []))
    if removed & set(ids):
        found.append("removed_photo_ids: a photo cannot be both live and removed")
    return found
