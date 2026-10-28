"""Two-stage recognition with atomic checkpoints and human precedence."""

from __future__ import annotations

import hashlib
import json
import re
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
# With faces: SFace's own same-person threshold is 0.363; agreeing with the body,
# a little less already picked the right bib. Alone, the body must lead by 0.05.
FACE_AGREES = 0.3
BODY_AGREES = 0.6
BODY_LEAD = 0.05


def engine_id(size: str = "small") -> str:
    """Saved bibs are reused only from the same models: another size reads again."""
    models = ",".join(CATALOG[k]["sha256"] for k in ocr_models(size))
    return "people-v2:" + hashlib.sha256(models.encode()).hexdigest()[:16]


@dataclass
class Report:
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    seeds: int = 0


def _loose(bib):
    """A protocol may pad or case a bib differently from the plate ("007", "a12")."""
    return re.sub(r"(?<!\d)0+(?=\d)", "", bib.upper())


def _classified(observation, method, lock, starters):
    state = observation.get("state", "candidate")
    if method == "ocr":
        # Derived again on every run, so a changed start protocol needs no new read.
        if starters:
            spelled = starters.get(_loose(observation["value"]))
            if spelled is None:
                return {**observation, "state": "rejected"}
            # The site matches bibs exactly: "012" read for starter "12" is "12".
            observation = {**observation, "value": spelled}
        # Any bib format is accepted alike: races use letters too ("A12").
        needed = ACCEPT_LONE_DIGIT if len(observation["value"]) == 1 else ACCEPT_OCR
        state = (
            "accepted"
            if (observation.get("confidence") or 0) >= needed
            else "candidate"
        )
    elif state == "rejected":
        return observation
    if lock:
        state = "candidate"
    return {**observation, "state": state}


def _merge(photo, method, observations, starters=None):
    manual = [b for b in photo["bibs"] if b["method"] == "manual"]
    reviewed = {b["value"] for b in manual}
    lock = photo.get("manual_review", {}).get("lock_accepted_set", False)
    retained = [b for b in photo["bibs"] if b["method"] not in (method, "manual")]
    accepted = {b["value"] for b in retained if b["state"] == "accepted"}
    choices = {}
    for observation in observations:
        observation = _classified(observation, method, lock, starters)
        value = observation["value"]
        if value in reviewed or value in accepted:
            continue
        if value not in choices or (observation.get("confidence") or 0) > (
            choices[value].get("confidence") or 0
        ):
            choices[value] = observation
    # The site takes at most MAX_BIBS_PER_PHOTO: bibs still in play keep their place
    # ahead of reads the protocol rejected, which then may not survive a cleared one.
    automatic = sorted(
        [*retained, *choices.values()],
        key=lambda b: (b["state"] != "rejected", b.get("confidence") or 0),
        reverse=True,
    )
    photo["bibs"] = manual + automatic[: max(0, MAX_BIBS_PER_PHOTO - len(manual))]


def _checkpoint(folder, index):
    indexer.update_counts(index)
    indexer.save(folder, index)


def _without_orphans(folder, index):
    """Drop suggestions of bibs no longer accepted anywhere, such as one the start
    protocol now rejects; a run with appearance recomputes them all anyway."""
    known = {
        b["value"]
        for p in index["photos"]
        for b in p["bibs"]
        if b["state"] == "accepted"
    }
    for photo in index["photos"]:
        photo["bibs"] = [
            b
            for b in photo["bibs"]
            if b["method"] != "appearance" or b["value"] in known
        ]
    _checkpoint(folder, index)


def _ocr(folder, index, engine, appearance, size, starters, progress, cancel, report):
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
                saved = [b for b in photo["bibs"] if b["method"] == "ocr"]
                _merge(photo, "ocr", saved, starters)
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
                _merge(photo, "ocr", observations, starters)
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
    seeds, references, owners, values = [], [], [], []
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
                    "INSERT INTO crops VALUES (?, ?, ?, ?, ?)",
                    (
                        photo["id"],
                        json.dumps(rider.region),
                        rider.vector.astype(np.float32).tobytes(),
                        _blob(rider.face),
                        json.dumps(sorted(bibs)),
                    ),
                )
    # Stable input order keeps equal-score suggestions deterministic across schedules.
    for photo in photos:
        for vector, face, known in db.execute(
            "SELECT vector, face, known_bibs FROM crops WHERE photo_id=?",
            (photo["id"],),
        ):
            for value in json.loads(known):
                values.append(value)
                owners.append(photo["id"])
                seeds.append(np.frombuffer(vector, dtype=np.float32))
                references.append(_vector(face))
    report.seeds = len(seeds)
    return values, owners, np.asarray(seeds, dtype=np.float32), references


def _blob(vector):
    return None if vector is None else vector.astype(np.float32).tobytes()


def _vector(blob):
    return None if blob is None else np.frombuffer(blob, dtype=np.float32)


def _likeness(references, face):
    """Face similarity to each reference; -2 where the reference shows no face."""
    return np.array([-2.0 if f is None else float(f @ face) for f in references])


def _best(scores, values, owners, photo_id):
    """The bib whose reference matches best, and its lead over the next bib.

    A reference on the same photo is another person, never this one.
    """
    best: dict[str, float] = {}
    for score, value, owner in zip(scores, values, owners, strict=True):
        if owner != photo_id and score > best.get(value, -2.0):
            best[value] = float(score)
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return None, -1.0, 0.0
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    return ranked[0][0], ranked[0][1], ranked[0][1] - second


def _face_matches(body, likeness, values, owners, photo_id):
    """A face and the body agree on one bib, or the body alone is sure and well
    ahead of any other bib: on the labelled races this found more people, at
    awards too, and suggested fewer wrong bibs than the body alone."""
    value, score, lead = _best(body, values, owners, photo_id)
    if likeness is not None:
        known, face, _ = _best(likeness, values, owners, photo_id)
        if known == value and face >= FACE_AGREES and score >= BODY_AGREES:
            return [(value, max(face, score))]
    if value is not None and score >= APPEARANCE_THRESHOLD and lead >= BODY_LEAD:
        return [(value, score)]
    return []


def _appearance(folder, index, engine, db, faces, progress, cancel, report):
    values, owners, seeds, references = _references(
        folder, index, engine, db, progress, cancel, report
    )
    for n, photo in enumerate(index["photos"], 1):
        check_cancel(cancel)
        progress("Matching rider appearance", n, len(index["photos"]))
        if photo["processing_state"] == "failed":
            continue
        _verify(folder, photo)
        observations = []
        for region, vector, face, known in db.execute(
            "SELECT region, vector, face, known_bibs FROM crops WHERE photo_id=?",
            (photo["id"],),
        ):
            if not len(seeds):
                break
            if json.loads(known):
                continue  # an unambiguous accepted bib already identifies this crop
            scores = seeds @ np.frombuffer(vector, dtype=np.float32)
            if faces:
                query = _vector(face)
                likeness = None if query is None else _likeness(references, query)
                matches = _face_matches(scores, likeness, values, owners, photo["id"])
            else:
                matches = [
                    (values[i], scores[i])
                    for i in np.flatnonzero(scores >= APPEARANCE_THRESHOLD)
                ]
            for value, score in matches:
                observations.append(
                    {
                        "value": value,
                        "method": "appearance",
                        "state": "candidate",
                        "confidence": float(np.clip(score, 0, 1)),
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
    faces: bool = False,
    starters: frozenset[str] = frozenset(),
) -> Report:
    """Mutate the worker's snapshot, refusing concurrent edits.

    OCR checkpoints survive cancellation. Vectors live in a private temporary database,
    removed on every exit. Restarting recomputes appearance. Read bibs that are not in
    ``starters`` (the start protocol, when given) are kept as rejected; the others are
    saved as the protocol spells them.
    """
    report = Report()
    spelling = {_loose(bib): bib for bib in starters}
    try:
        _ocr(
            folder, index, engine, appearance, size, spelling, progress, cancel, report
        )
        if appearance:
            with tempfile.TemporaryDirectory(prefix="photo-appearance-") as temp:
                with closing(sqlite3.connect(str(Path(temp) / "crops.sqlite3"))) as db:
                    db.execute(
                        "CREATE TABLE crops (photo_id TEXT, region TEXT,"
                        " vector BLOB, face BLOB, known_bibs TEXT)"
                    )
                    db.execute("CREATE INDEX crop_photo ON crops(photo_id)")
                    _appearance(
                        folder, index, engine, db, faces, progress, cancel, report
                    )
        elif spelling:
            _without_orphans(folder, index)
    except CancelledError:
        report.cancelled = True
    return report
