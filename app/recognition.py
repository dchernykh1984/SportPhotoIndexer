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

from app import indexer
from app.index_format import MAX_BIBS_PER_PHOTO
from app.model_cache import CATALOG, CancelledError, check_cancel, ocr_models
from app.parallel import ChangedPhotoError as ChangedPhotoError
from app.parallel import results
from app.parallel import verify as _verify
from app.vision import ACCEPT_LONE_DIGIT, ACCEPT_OCR, contains

APPEARANCE_THRESHOLD = 0.8


def engine_id(size: str = "small") -> str:
    """Saved bibs are reused only from the same models: another size reads again."""
    models = ",".join(CATALOG[k]["sha256"] for k in ocr_models(size))
    return "people-v2:" + hashlib.sha256(models.encode()).hexdigest()[:16]


@dataclass
class Report:
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    seeds: int = 0


def _classified(observation, method, lock):
    state = observation.get("state", "candidate")
    if state == "rejected":
        return observation
    if method == "ocr":
        # Any bib format is accepted alike: races use letters too ("A12").
        needed = ACCEPT_LONE_DIGIT if len(observation["value"]) == 1 else ACCEPT_OCR
        state = (
            "accepted"
            if (observation.get("confidence") or 0) >= needed
            else "candidate"
        )
    if lock:
        state = "candidate"
    return {**observation, "state": state}


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
        observation = _classified(observation, method, lock)
        if value not in choices or (observation.get("confidence") or 0) > (
            choices[value].get("confidence") or 0
        ):
            choices[value] = observation
    automatic = sorted(
        [*retained, *choices.values()],
        key=lambda b: b.get("confidence") or 0,
        reverse=True,
    )
    photo["bibs"] = manual + automatic[: max(0, MAX_BIBS_PER_PHOTO - len(manual))]


def _checkpoint(folder, index):
    indexer.update_counts(index)
    indexer.save(folder, index)


def _ocr(folder, index, engine, appearance, size, progress, cancel, report):
    engine_name = engine_id(size)
    total = len(index["photos"])
    pending = []
    cached = 0
    for photo in index["photos"]:
        check_cancel(cancel)
        stamp = {"sha256": photo["original"]["sha256"], "engine": engine_name}
        if photo.get("recognition", {}).get("ocr") != stamp:
            pending.append(photo)
        else:
            cached += 1
            progress("Checking saved bib numbers", cached, total)
            check_cancel(cancel)
            try:
                _verify(folder, photo)
                _merge(photo, "ocr", [b for b in photo["bibs"] if b["method"] == "ocr"])
                photo.pop("recognition_error", None)
                photo["processing_state"] = "pending" if appearance else "processed"
            except OSError as exc:
                photo["processing_state"] = "failed"
                photo["recognition_error"] = str(exc)[:500]
                report.errors.append(f"{photo['original']['path']}: {exc}")
            _checkpoint(folder, index)
    completed = total - len(pending)
    with closing(results(folder, pending, engine, "ocr", cancel)) as computed:
        for photo, (readings, error) in computed:
            progress("Reading bib numbers", completed + 1, total)
            check_cancel(cancel)
            if not error:
                _verify(folder, photo)
                observations = [
                    {
                        "value": r.value,
                        "confidence": float(r.confidence),
                        "region": dict(
                            zip(("x", "y", "w", "h"), r.region, strict=True)
                        ),
                        "method": "ocr",
                    }
                    for r in readings
                ]
                photo.setdefault("recognition", {})["ocr"] = {
                    "sha256": photo["original"]["sha256"],
                    "engine": engine_name,
                }
                _merge(photo, "ocr", observations)
                photo.pop("recognition_error", None)
                photo["processing_state"] = "pending" if appearance else "processed"
            else:
                photo["processing_state"] = "failed"
                photo["recognition_error"] = error
                report.errors.append(f"{photo['original']['path']}: {error}")
            _checkpoint(folder, index)
            completed += 1
    if not pending:
        _checkpoint(folder, index)


def _known_bibs(photo, riders):
    known = [set() for _ in riders]
    for bib in photo["bibs"]:
        if bib["state"] != "accepted" or bib["method"] == "appearance":
            continue
        region = bib.get("region")
        if region:
            box = tuple(region[k] for k in ("x", "y", "w", "h"))
            owners = [
                i for i, rider in enumerate(riders) if contains(rider.region, box)
            ]
        elif bib["method"] == "manual" and len(indexer.bibs_of(photo)) == 1:
            owners = list(range(len(riders)))
        else:
            owners = []
        if len(owners) == 1:
            known[owners[0]].add(bib["value"])
    return known


def _references(folder, index, engine, db, progress, cancel, report):
    seeds, values = [], []
    photos = [p for p in index["photos"] if p["processing_state"] != "failed"]
    with closing(results(folder, photos, engine, "riders", cancel)) as computed:
        for n, (photo, (riders, error)) in enumerate(computed, 1):
            progress("Finding rider references", n, len(photos))
            check_cancel(cancel)
            if error:
                photo["processing_state"] = "failed"
                report.errors.append(f"{photo['original']['path']}: {error}")
                _checkpoint(folder, index)
                continue
            _verify(folder, photo)
            for rider, bibs in zip(riders, _known_bibs(photo, riders), strict=True):
                db.execute(
                    "INSERT INTO crops VALUES (?, ?, ?, ?)",
                    (
                        photo["id"],
                        json.dumps(rider.region),
                        rider.vector.astype(np.float32).tobytes(),
                        json.dumps(sorted(bibs)),
                    ),
                )
    # Stable input order keeps equal-score suggestions deterministic across schedules.
    for photo in photos:
        for vector, known in db.execute(
            "SELECT vector, known_bibs FROM crops WHERE photo_id=?", (photo["id"],)
        ):
            for value in json.loads(known):
                values.append(value)
                seeds.append(np.frombuffer(vector, dtype=np.float32))
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
        for region, vector, known in db.execute(
            "SELECT region, vector, known_bibs FROM crops WHERE photo_id=?",
            (photo["id"],),
        ):
            if not len(seeds):
                break
            if json.loads(known):
                continue  # an unambiguous accepted bib already identifies this crop
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
    size: str = "small",
) -> Report:
    """Mutate the worker's snapshot, refusing concurrent edits.

    OCR checkpoints survive cancellation. Vectors live in a private temporary database,
    removed on every exit. Restarting recomputes appearance.
    """
    report = Report()
    try:
        _ocr(folder, index, engine, appearance, size, progress, cancel, report)
        if appearance:
            with tempfile.TemporaryDirectory(prefix="photo-appearance-") as temp:
                with closing(sqlite3.connect(str(Path(temp) / "crops.sqlite3"))) as db:
                    db.execute(
                        "CREATE TABLE crops "
                        "(photo_id TEXT, region TEXT, vector BLOB, known_bibs TEXT)"
                    )
                    db.execute("CREATE INDEX crop_photo ON crops(photo_id)")
                    _appearance(folder, index, engine, db, progress, cancel, report)
    except CancelledError:
        report.cancelled = True
    return report
