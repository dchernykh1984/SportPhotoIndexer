"""The photo-index.v1.json format, and the same checks the site applies to it.

The contract lives in cycling-site, ``specs/349-external-photo-albums/contracts/
photo-index.md``. ``problems`` returns what the site would refuse, field by field, so
the indexer never writes an index the site cannot import.
"""

from __future__ import annotations

import json
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
_VIEW_URL = re.compile(
    r"^https://(www\.dropbox\.com|dl\.dropboxusercontent\.com)/scl/fi/[^\s]+\Z"
)


def _member(value: object, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError, TypeError:
        return None


def _text_problem(value: object) -> bool:
    if isinstance(value, str):
        return "\x00" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value)
    if isinstance(value, dict):
        return any(_text_problem(k) or _text_problem(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_text_problem(v) for v in value)
    return False


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
    found: list[str] = []
    if why := path_problem(asset.get("path")):
        found.append(f"{where}.path: {why}")
    if not isinstance(asset.get("sha256"), str) or not _SHA.match(asset["sha256"]):
        found.append(f"{where}.sha256: must be the file's SHA-256")
    size = asset.get("bytes")
    if type(size) is not int or not 1 <= size < 2**63:
        found.append(f"{where}.bytes: must be a positive integer")
    if not _member(asset.get("media_type"), set(MEDIA_TYPES.values())):
        found.append(f"{where}.media_type: must be JPEG, PNG or WebP")
    url = asset.get("view_url", "")
    if not isinstance(url, str) or (
        url and (len(url) > MAX_PATH or not _VIEW_URL.fullmatch(url))
    ):
        found.append(f"{where}.view_url: must be a Dropbox shared file link")
    return found


def _bib_problems(bib: object, where: str, original_sha: object) -> list[str]:
    if not isinstance(bib, dict) or not isinstance(bib.get("value"), str):
        return [f"{where}: not a bib"]
    found: list[str] = []
    if why := bib_problem(bib["value"]):
        found.append(f"{where}.value: {why}")
    if not _member(bib.get("state"), _STATES):
        found.append(f"{where}.state: must be candidate, accepted or rejected")
    if not _member(bib.get("method"), _METHODS):
        found.append(f"{where}.method: must be ocr, appearance or manual")
    if bib.get("method") == "manual" and bib.get("content_sha256") != original_sha:
        found.append(f"{where}.content_sha256: must be the original's SHA-256")
    if bib.get("method") == "appearance" and bib.get("state") != "candidate":
        found.append(f"{where}.state: an appearance match is always a candidate")
    confidence = bib.get("confidence")
    if confidence is not None and not (
        isinstance(confidence, int | float) and 0 <= confidence <= 1
    ):
        found.append(f"{where}.confidence: must be between 0 and 1")
    if "region" in bib:
        found += _region_problems(bib["region"], f"{where}.region")
    return found


def _region_problems(region, where):
    if not isinstance(region, dict):
        return [f"{where}: must be an x, y, w, h object"]
    values = [region.get(key) for key in ("x", "y", "w", "h")]
    if any(type(v) not in (int, float) or not 0 <= v <= 1 for v in values):
        return [f"{where}: coordinates must be fractions between 0 and 1"]
    x, y, w, h = values
    if not w or not h or x + w > 1.000001 or y + h > 1.000001:
        return [f"{where}: box must fit inside the image"]
    return []


def _review_problems(photo, where, original_sha):
    review = photo.get("manual_review")
    if review is None:
        return []
    if not isinstance(review, dict) or review.get("original_sha256") != original_sha:
        return [f"{where}.manual_review: must name the original's SHA-256"]
    if not isinstance(review.get("lock_accepted_set"), bool):
        return [f"{where}.manual_review.lock_accepted_set: must be true or false"]
    rid = review.get("review_id")
    if not isinstance(rid, str) or not 1 <= len(rid) <= 100:
        return [f"{where}.manual_review.review_id: must be a correction ID"]
    bibs = [
        b
        for b in photo.get("bibs", [])
        if isinstance(b, dict) and isinstance(b.get("value"), str)
    ]
    accepted = {
        normalize_bib(b["value"])
        for b in bibs
        if b.get("method") == "manual" and b.get("state") == "accepted"
    }
    if review["lock_accepted_set"] and any(
        b.get("state") == "accepted" and normalize_bib(b["value"]) not in accepted
        for b in bibs
    ):
        return [f"{where}.bibs: automatic matches extend the manually accepted set"]
    return []


def _photo_problems(photo: object, where: str) -> list[str]:
    if not isinstance(photo, dict):
        return [f"{where}: not a photo"]
    found: list[str] = []
    if _uuid(photo.get("id")) is None:
        found.append(f"{where}.id: not a UUID")
    found += _asset_problems(photo.get("original"), f"{where}.original")
    if photo.get("preview") is not None:
        found += _asset_problems(photo["preview"], f"{where}.preview")
    if not _member(photo.get("processing_state"), _PROCESSING):
        found.append(f"{where}.processing_state: must be pending, processed or failed")
    bibs = photo.get("bibs", [])
    if not isinstance(bibs, list) or len(bibs) > MAX_BIBS_PER_PHOTO:
        return [*found, f"{where}.bibs: at most {MAX_BIBS_PER_PHOTO}"]
    original = photo.get("original")
    original_sha = original.get("sha256") if isinstance(original, dict) else None
    for j, bib in enumerate(bibs):
        found += _bib_problems(bib, f"{where}.bibs[{j}]", original_sha)
    found += _review_problems(photo, where, original_sha)
    return found


def problems(index: dict) -> list[str]:
    """Everything the site would refuse in this index; empty when it is fine."""
    if not isinstance(index, dict):
        return ["index: must be an object"]
    try:
        if _text_problem(index):
            return ["index: contains NUL or an unpaired Unicode surrogate"]
        encoded = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > MAX_INDEX_BYTES:
            return [f"index: larger than {MAX_INDEX_BYTES} bytes"]
    except TypeError, ValueError, RecursionError:
        return ["index: invalid or nested too deeply"]
    return _header_problems(index) + _inventory_problems(index)


def _header_problems(index: dict) -> list[str]:
    found: list[str] = []
    if (
        type(index.get("schema_version")) is not int
        or index["schema_version"] != SCHEMA_VERSION
    ):
        found.append(f"schema_version: must be {SCHEMA_VERSION}")
    if _uuid(index.get("album_id")) is None:
        found.append("album_id: not a UUID")
    if index.get("bib_normalization") != BIB_NORMALIZATION:
        found.append(f"bib_normalization: must be {BIB_NORMALIZATION}")
    revision = index.get("revision")
    if type(revision) is not int or not 1 <= revision < 2**63:
        found.append("revision: must be a positive integer")
    processing = index.get("processing")
    if not isinstance(processing, dict) or not isinstance(
        processing.get("inventory_complete"), bool
    ):
        found.append("processing.inventory_complete: must be true or false")
    return found


def _inventory_problems(index: dict) -> list[str]:
    found: list[str] = []
    photos = index.get("photos")
    if not isinstance(photos, list):
        return [*found, "photos: must be a list"]
    if len(photos) > MAX_PHOTOS:
        found.append(f"photos: more than {MAX_PHOTOS}")
    for i, photo in enumerate(photos):
        found += _photo_problems(photo, f"photos[{i}]")
    ids = [_uuid(p.get("id")) for p in photos if isinstance(p, dict)]
    if len(set(ids)) != len(ids):
        found.append("photos: a photo id repeats")
    paths = [
        unicodedata.normalize("NFC", p["original"]["path"])
        for p in photos
        if isinstance(p, dict)
        and isinstance(p.get("original"), dict)
        and isinstance(p["original"].get("path"), str)
    ]
    if len(set(paths)) != len(paths):
        found.append("photos: two photos name the same original")
    raw_removed = index.get("removed_photo_ids", [])
    if not isinstance(raw_removed, list):
        return [*found, "removed_photo_ids: must be a list"]
    removed = {_uuid(v) for v in raw_removed}
    if None in removed:
        found.append("removed_photo_ids: not a UUID")
    if removed & set(ids):
        found.append("removed_photo_ids: a photo cannot be both live and removed")
    return found
