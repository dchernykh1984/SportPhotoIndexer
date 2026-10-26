"""Two-stage recognition with atomic checkpoints and human precedence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app import indexer
from app.index_format import MAX_BIBS_PER_PHOTO
from app.model_cache import CATALOG, OCR_MODELS, CancelledError, check_cancel
from app.vision import contains

ENGINE_ID = (
    "tiles768-v1:"
    + hashlib.sha256(
        ",".join(CATALOG[k]["sha256"] for k in OCR_MODELS).encode()
    ).hexdigest()[:16]
)
ACCEPT_OCR = 0.95
APPEARANCE_THRESHOLD = 0.8


@dataclass
class Report:
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    seeds: int = 0


class ChangedPhotoError(indexer.IndexError_):
    pass


def _verify(folder, photo):
    path = folder / photo["original"]["path"]
    if indexer.sha256_of(path) != photo["original"]["sha256"]:
        raise ChangedPhotoError(
            f"{path.name} changed; rescan the folder before recognition"
        )
    return path


def _open(folder, photo):
    with Image.open(_verify(folder, photo)) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


def _merge(photo, method, observations):
    manual = [b for b in photo["bibs"] if b["method"] == "manual"]
    reviewed = {b["value"] for b in manual}
    lock = photo.get("manual_review", {}).get("lock_accepted_set", False)
    retained = [b for b in photo["bibs"] if b["method"] not in (method, "manual")]
    accepted = {b["value"] for b in retained if b["state"] == "accepted"}
    choices = {}
    for observation in observations:
        value = observation["value"]
        if value in reviewed or value in accepted:
            continue
        if lock:
            observation = {**observation, "state": "candidate"}
        if (
            value not in choices
            or observation["confidence"] > choices[value]["confidence"]
        ):
            choices[value] = observation
    automatic = sorted(
        [*retained, *choices.values()],
        key=lambda b: b.get("confidence", 0),
        reverse=True,
    )
    photo["bibs"] = manual + automatic[: max(0, MAX_BIBS_PER_PHOTO - len(manual))]


def _checkpoint(folder, index):
    indexer.update_counts(index)
    indexer.save(folder, index)


def _ocr(folder, index, engine, appearance, progress, cancel, report):
    total = len(index["photos"])
    for n, photo in enumerate(index["photos"], 1):
        check_cancel(cancel)
        progress("Reading bib numbers", n, total)
        stamp = {"sha256": photo["original"]["sha256"], "engine": ENGINE_ID}
        try:
            _verify(folder, photo)
            metadata = photo.setdefault("recognition", {})
            if metadata.get("ocr") != stamp:
                with _open(folder, photo) as image:
                    readings = engine.ocr(image)
                check_cancel(cancel)
                _verify(folder, photo)
                _merge(
                    photo,
                    "ocr",
                    [
                        {
                            "value": r.value,
                            "confidence": float(r.confidence),
                            "region": dict(
                                zip(("x", "y", "w", "h"), r.region, strict=True)
                            ),
                            "method": "ocr",
                            "state": "accepted"
                            if r.confidence >= ACCEPT_OCR
                            else "candidate",
                        }
                        for r in readings
                    ],
                )
                metadata["ocr"] = stamp
            photo.pop("recognition_error", None)
            photo["processing_state"] = "pending" if appearance else "processed"
        except (OSError, Image.DecompressionBombError) as exc:
            photo["processing_state"] = "failed"
            photo["recognition_error"] = str(exc)[:500]
            report.errors.append(f"{photo['original']['path']}: {exc}")
        _checkpoint(folder, index)


def _seed_values(photo, riders):
    for bib in photo["bibs"]:
        if bib["state"] != "accepted" or bib["method"] == "appearance":
            continue
        region = bib.get("region")
        if region:
            box = tuple(region[k] for k in ("x", "y", "w", "h"))
            owners = [r for r in riders if contains(r.region, box)]
        elif bib["method"] == "manual" and len(indexer.bibs_of(photo)) == 1:
            owners = riders
        else:
            owners = []
        if len(owners) == 1:
            yield bib["value"], owners[0].vector


def _references(folder, index, engine, db, progress, cancel, report):
    seeds, values = [], []
    for n, photo in enumerate(index["photos"], 1):
        check_cancel(cancel)
        progress("Finding rider references", n, len(index["photos"]))
        if photo["processing_state"] == "failed":
            continue
        try:
            with _open(folder, photo) as image:
                riders = engine.riders(image)
            check_cancel(cancel)
            _verify(folder, photo)
            for rider in riders:
                db.execute(
                    "INSERT INTO crops VALUES (?, ?, ?)",
                    (
                        photo["id"],
                        json.dumps(rider.region),
                        rider.vector.astype(np.float32).tobytes(),
                    ),
                )
            for value, vector in _seed_values(photo, riders):
                values.append(value)
                seeds.append(vector)
        except (OSError, Image.DecompressionBombError) as exc:
            photo["processing_state"] = "failed"
            report.errors.append(f"{photo['original']['path']}: {exc}")
            _checkpoint(folder, index)
    report.seeds = len(seeds)
    return values, np.asarray(seeds, dtype=np.float32)


def _appearance(folder, index, engine, db, progress, cancel, report):
    values, seeds = _references(folder, index, engine, db, progress, cancel, report)
    for n, photo in enumerate(index["photos"], 1):
        check_cancel(cancel)
        progress("Matching rider appearance", n, len(index["photos"]))
        if photo["processing_state"] == "failed":
            continue
        _verify(folder, photo)
        observations = []
        for region, vector in db.execute(
            "SELECT region, vector FROM crops WHERE photo_id=?", (photo["id"],)
        ):
            if not len(seeds):
                break
            scores = seeds @ np.frombuffer(vector, dtype=np.float32)
            for i in np.flatnonzero(scores >= APPEARANCE_THRESHOLD):
                observations.append(
                    {
                        "value": values[i],
                        "method": "appearance",
                        "state": "candidate",
                        "confidence": float(np.clip(scores[i], 0, 1)),
                        "region": dict(
                            zip(("x", "y", "w", "h"), json.loads(region), strict=True)
                        ),
                    }
                )
        _merge(photo, "appearance", observations)
        photo["processing_state"] = "processed"
        _checkpoint(folder, index)


def run(
    folder: Path,
    index: dict,
    engine,
    *,
    appearance: bool,
    progress: Callable[[str, int, int], None],
    cancel: Callable[[], bool],
) -> Report:
    """Mutate the worker's snapshot, refusing concurrent edits.

    OCR checkpoints survive cancellation. Vectors live in a private temporary database,
    removed on every exit. Restarting recomputes appearance.
    """
    report = Report()
    try:
        _ocr(folder, index, engine, appearance, progress, cancel, report)
        if appearance:
            with tempfile.TemporaryDirectory(prefix="photo-appearance-") as temp:
                with closing(sqlite3.connect(str(Path(temp) / "crops.sqlite3"))) as db:
                    db.execute(
                        "CREATE TABLE crops (photo_id TEXT, region TEXT, vector BLOB)"
                    )
                    db.execute("CREATE INDEX crop_photo ON crops(photo_id)")
                    _appearance(folder, index, engine, db, progress, cancel, report)
    except CancelledError:
        report.cancelled = True
    return report
