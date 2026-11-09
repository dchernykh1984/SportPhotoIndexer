"""Two-stage recognition with atomic checkpoints and human precedence."""

from __future__ import annotations

import calendar
import hashlib
import itertools
import json
import re
import sqlite3
import tempfile
from collections.abc import Callable
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from app import indexer
from app.index_format import MAX_BIBS_PER_PHOTO
from app.model_cache import CATALOG, SIZES, CancelledError, check_cancel, ocr_models
from app.parallel import ChangedPhotoError as ChangedPhotoError
from app.parallel import results
from app.parallel import verify as _verify
from app.vision import ACCEPT_LONE_DIGIT, ACCEPT_OCR, READ_VERSIONS, contains

APPEARANCE_THRESHOLD = 0.8
# With faces: SFace's own same-person threshold is 0.363; agreeing with the body,
# a little less already picked the right bib. Alone, the body must lead by 0.05.
FACE_AGREES = 0.3
BODY_AGREES = 0.6
BODY_LEAD = 0.05
# Photos one camera took at most BURST_SECONDS apart often show a rider again, further
# away or turned, with no bib to read. A person who matches a person of the other
# photo best, and back, at BURST_LIKENESS or more, and stands about where they stood
# (moved by at most BURST_SHIFT of the width, at most twice as tall or short) is taken
# for the same person, and so on along the series: a bib known for one of them is
# offered for the others. On the BMX race 19 more right suggestions for 6 wrong ones.
BURST_SECONDS = 3
BURST_LIKENESS = 0.65
BURST_SHIFT = 0.3


def engine_id(size: str = "small") -> str:
    """Saved bibs are reused only from the same models: another size reads again."""
    models = ",".join(CATALOG[k]["sha256"] for k in ocr_models(size))
    version = READ_VERSIONS[bool(SIZES[size])]
    return f"{version}:" + hashlib.sha256(models.encode()).hexdigest()[:16]


@dataclass
class Report:
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    seeds: int = 0


def _loose(bib):
    """A protocol may pad or case a bib differently from the plate ("007", "a12")."""
    return re.sub(r"(?<!\d)0+(?=\d)", "", bib.upper())


def _lone(bib):
    """One digit as the protocol compares bibs: a "7" read and spelled "007" too."""
    return len(_loose(bib)) == 1


def _sure(observation):
    """Read surely enough to be accepted: a lone digit needs more."""
    needed = ACCEPT_LONE_DIGIT if _lone(observation["value"]) else ACCEPT_OCR
    return (observation.get("confidence") or 0) >= needed


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
        state = "accepted" if _sure(observation) else "candidate"
    elif state == "rejected":
        return observation
    if lock:
        state = "candidate"
    return {**observation, "state": state}


def _one_size(ra, rb):
    """Two boxes of one height."""
    low, high = sorted((ra["h"], rb["h"]))
    return 0 < high <= 1.5 * low


def _one_row(ra, rb):
    """Two boxes of one height at one height."""
    return (
        _one_size(ra, rb)
        and abs(ra["y"] + ra["h"] / 2 - rb["y"] - rb["h"] / 2)
        <= max(ra["h"], rb["h"]) / 2
    )


def _follows(a, b):
    """b is the number after a, printed right of it in one row, apart from it: the
    pieces of one bib read on their own touch each other. Widths measure the gap, so
    the photo's shape does not (the narrowest gap on the Sokol board was 0.13)."""
    ra, rb = a["region"], b["region"]
    return (
        int(b["value"]) == int(a["value"]) + 1
        and rb["x"] - (ra["x"] + ra["w"]) >= 0.1 * min(ra["w"], rb["w"])
        and _one_row(ra, rb)
    )


def _close(a, b):
    """Printed close as on a board, not plates on riders side by side: centres at most
    four widths apart (1 to 3.7 on the Sokol board; riders stand wider)."""
    ra, rb = a["region"], b["region"]
    apart = rb["x"] + rb["w"] / 2 - ra["x"] - ra["w"] / 2
    return apart <= 4 * max(ra["w"], rb["w"])


def _steps(two, three, sure):
    """2 and 3 alone in their row but for the winner's 1 between them, as on a
    podium: riders 2 and 3 on a start line stand among other riders' bibs."""
    left, right = two["region"]["x"], three["region"]["x"]
    return not any(
        o is not two
        and o is not three
        and (
            _one_row(o["region"], two["region"])
            or _one_row(o["region"], three["region"])
        )
        and not (_loose(o["value"]) == "1" and left < o["region"]["x"] < right)
        for o in sure
    )


def _printed(observations):
    """The reads that are print in rows of numbers, not riders' bibs: following
    numbers at most four widths apart in two rows of one size make a sign-in board,
    and 2 and 3 alone in their row a podium's steps. One row, or rows standing wider
    apart, as riders mostly do, may be riders; riders packed closer in two rows look
    like a board. Every read of that print's size counts. On the Sokol race such
    photos held over half of the accepted reads nobody wore."""
    # Decimal, not any digit: an edited index may hold a "2" written small, which
    # int() refuses.
    numbers = [o for o in observations if o["value"].isdecimal() and o.get("region")]
    # Only reads sure enough to be accepted: a weak misread beside a bib is no print.
    sure = [o for o in numbers if _sure(o)]
    pairs = [(a, b) for a, b in itertools.permutations(sure, 2) if _follows(a, b)]
    close = [(a, b) for a, b in pairs if _close(a, b)]
    # Another row of the same print: two teammates close in front and two more far
    # behind are rows of two sizes.
    board = [
        (a, b)
        for a, b in close
        if any(
            _one_size(a["region"], c["region"])
            and not _one_row(a["region"], c["region"])
            for c, _ in close
        )
    ]
    podium = [
        (a, b)
        for a, b in pairs
        if (_loose(a["value"]), _loose(b["value"])) == ("2", "3")
        # Or a board's row 1, 2, 3 printed close together.
        and (_steps(a, b, sure) or any(d is a or c is b for c, d in close))
    ]
    if not board and not podium:
        return []
    # The print's own size: riders' following bibs beside it are no print.
    heights = [r["region"]["h"] for pair in board + podium for r in pair]
    low, high = min(heights) / 1.5, max(heights) * 1.5
    return [o for o in numbers if low <= o["region"]["h"] <= high]


def _same_spot(a, b):
    """At least half of the smaller read's box inside the other's."""
    ra, rb = a["region"], b["region"]
    width = min(ra["x"] + ra["w"], rb["x"] + rb["w"]) - max(ra["x"], rb["x"])
    height = min(ra["y"] + ra["h"], rb["y"] + rb["h"]) - max(ra["y"], rb["y"])
    smaller = min(ra["w"] * ra["h"], rb["w"] * rb["h"])
    return width > 0 and height > 0 and width * height >= 0.5 * smaller


def _misreads(observations, starters):
    """The reads of a spot that a surer read of another value holds: one sticker read
    as 39 and as 33. On the BMX race the less sure read was wrong all 44 times. A
    value the start protocol rejects holds no spot, and "6" read inside "16" is left
    to the reader, which keeps the longer one."""
    held = sorted(
        (
            o
            for o in observations
            if o.get("region") and (not starters or _loose(o["value"]) in starters)
        ),
        key=lambda o: o.get("confidence") or 0,
        reverse=True,
    )
    found: set[int] = set()
    for o in held:
        if any(
            id(k) not in found
            and (k.get("confidence") or 0) > (o.get("confidence") or 0)
            and k["value"] not in o["value"]
            and o["value"] not in k["value"]
            and _same_spot(k, o)
            for k in held
        ):
            found.add(id(o))
    return found


def _rank(observation):
    return (observation["state"] == "accepted", observation.get("confidence") or 0)


def _merge(photo, method, observations, starters=None):
    manual = [b for b in photo["bibs"] if b["method"] == "manual"]
    reviewed = {b["value"] for b in manual}
    lock = photo.get("manual_review", {}).get("lock_accepted_set", False)
    retained = [b for b in photo["bibs"] if b["method"] not in (method, "manual")]
    accepted = {b["value"] for b in retained if b["state"] == "accepted"}
    choices = {}
    printed, before, misread = set(), set(), set()
    if method == "ocr":
        printed = {id(o) for o in _printed(observations)}
        # Rejected, not dropped: like the protocol's, derived again on every run.
        misread = _misreads(observations, starters)
        # The saved reads found to be print stay print on later runs, whatever the
        # protocol or thresholds then say: a rerun sees the saved reads only, one per
        # value and twenty at most, where the board's pairs may be gone. One per value
        # also lets the value name the read.
        before = set(photo.get("recognition", {}).get("printed", []))
    print_values = {}
    for read in observations:
        observation = _classified(read, method, lock, starters)
        if id(read) in misread:
            # A sure read beaten on its spot is still offered for review: on the
            # Sokol race 9 of 26 such were the right bib (31 under a surer 37).
            state = "candidate" if _sure(observation) else "rejected"
            observation = {**observation, "state": state}
        is_print = id(read) in printed or read["value"] in before
        if is_print and observation["state"] == "accepted":
            observation = {**observation, "state": "candidate"}  # for review only
        value = observation["value"]
        if value in reviewed or value in accepted:
            continue
        # An accepted read of a value wins over a surer one demoted as print: the
        # board's 54 must not take the place of the 54 on a rider's plate.
        if value not in choices or _rank(observation) > _rank(choices[value]):
            choices[value] = observation
            print_values[value] = is_print
    # The site takes at most MAX_BIBS_PER_PHOTO: accepted bibs keep their place ahead
    # of candidates, such as a board's surer numbers held back, and bibs still in play
    # ahead of reads the protocol rejected, which then may not survive a cleared one.
    automatic = sorted(
        [*retained, *choices.values()],
        key=lambda b: (b["state"] != "rejected", *_rank(b)),
        reverse=True,
    )
    photo["bibs"] = manual + automatic[: max(0, MAX_BIBS_PER_PHOTO - len(manual))]
    if method == "ocr":
        kept = [
            b["value"]
            for b in photo["bibs"]
            if b["method"] == "ocr" and print_values.get(b["value"])
        ]
        recognition = photo.setdefault("recognition", {})
        if kept:
            recognition["printed"] = kept
        else:
            recognition.pop("printed", None)


def _checkpoint(folder, index):
    indexer.update_counts(index)
    indexer.save(folder, index)


@contextmanager
def _saved_once(folder, index, report):
    """Save the index once when a pass ends, also when it is stopped: each save
    rewrites the whole index. An error that ends the pass wins over one the save
    raises then, so a Stop still reads as a Stop; the save's error is reported."""
    try:
        yield
    except BaseException:
        try:
            _checkpoint(folder, index)
        except (indexer.IndexError_, OSError) as exc:
            report.errors.append(f"{indexer.INDEX_FILE} not saved: {exc}")
        raise
    _checkpoint(folder, index)


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
    with _saved_once(folder, index, report):  # before the new reads, too
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
                # New reads, so what was print among the old ones no longer counts.
                photo["recognition"] = {
                    "ocr": {
                        "sha256": photo["original"]["sha256"],
                        "engine": engine_name,
                    }
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


def _known_bibs(photo, riders):
    """Each rider's accepted bibs, with the method that gave them."""
    known: list[dict[str, str]] = [{} for _ in riders]
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
            known[owners[0]].setdefault(bib["value"], bib["method"])
    return known


def _trusted(known):
    """The bibs that name a rider: a lone digit read by OCR is too often a logo, a
    finger or a piece of a longer bib (7% right on the Sokol race); a typed one is
    sure."""
    return [v for v, method in known.items() if method == "manual" or not _lone(v)]


def _shot(path: Path) -> tuple[tuple[str, str], int] | None:
    """The camera and the second a photo was taken, from its EXIF; None when either is
    missing. Never the file's own dates: every copy or export rewrites them."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            details = exif.get_ifd(0x8769)  # the Exif IFD
            model = str(exif.get(272) or "").strip("\x00 ")
            serial = str(details.get(42033) or "").strip("\x00 ")
            taken = str(details.get(36867)).strip("\x00 ")  # DateTimeOriginal
        moment = datetime.strptime(taken, "%Y:%m:%d %H:%M:%S")
    except Exception:  # no EXIF, or a damaged one: it fails in many ways
        return None
    return ((model, serial), calendar.timegm(moment.timetuple())) if model else None


def _references(folder, index, engine, db, progress, cancel, report):
    seeds, references, owners, values = [], [], [], []
    people, shots = [], {}
    photos = [p for p in index["photos"] if p["processing_state"] != "failed"]
    with closing(results(folder, photos, engine, "riders", cancel)) as computed:
        for n, (photo, (riders, error)) in enumerate(computed, 1):
            progress("Finding rider references", n, len(photos))
            check_cancel(cancel)
            if error:
                # Saved with the whole pass, once, by _appearance.
                photo["processing_state"] = "failed"
                photo["recognition_error"] = error
                report.errors.append(f"{photo['original']['path']}: {error}")
                continue
            shots[photo["id"]] = _shot(folder / photo["original"]["path"])
            # The worker checked the photo before and after; matching checks it again
            # when its suggestions are written.
            for rider, bibs in zip(riders, _known_bibs(photo, riders), strict=True):
                db.execute(
                    "INSERT INTO crops VALUES (?, ?, ?, ?, ?)",
                    (
                        photo["id"],
                        json.dumps(rider.region),
                        rider.vector.astype(np.float32).tobytes(),
                        _blob(rider.face),
                        json.dumps(bibs, sort_keys=True),
                    ),
                )
    # Stable input order keeps equal-score suggestions deterministic across schedules.
    for photo in photos:
        for region, vector, face, known in db.execute(
            "SELECT region, vector, face, known_bibs FROM crops WHERE photo_id=?",
            (photo["id"],),
        ):
            # Two bibs left in one rider's box name neither of them for sure.
            trusted = _trusted(json.loads(known))
            body = np.frombuffer(vector, dtype=np.float32)
            people.append(_Person(photo["id"], region, body, trusted))
            if len(trusted) == 1:
                values.extend(trusted)
                owners.append(photo["id"])
                seeds.append(body)
                references.append(_vector(face))
    report.seeds = len(seeds)
    named = _named(people, _chains(people, shots))
    return values, owners, np.asarray(seeds, dtype=np.float32), references, named


class _Person(NamedTuple):
    photo_id: str
    region: str  # as saved, JSON
    body: np.ndarray
    bibs: list[str]  # the trusted ones


def _same_place(a, b):
    """About where the other photo showed them: no further than BURST_SHIFT of the
    width across, and at most twice as tall or short."""
    (ax, _, aw, ah), (bx, _, bw, bh) = json.loads(a), json.loads(b)
    return abs(ax + aw / 2 - bx - bw / 2) <= BURST_SHIFT and max(ah, bh) <= 2 * min(
        ah, bh
    )


def _chains(people, shots):
    """One person over a camera's photos taken close together: lists of indices into
    ``people`` (in index order), two or more each and never two of one photo.
    ``shots`` maps a photo id to its camera and second, or None."""
    parent = list(range(len(people)))
    photos_of = [{person.photo_id} for person in people]
    on_photo: dict[str, list[int]] = {}
    for i, person in enumerate(people):
        on_photo.setdefault(person.photo_id, []).append(i)

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        i, j = root(i), root(j)
        if i != j and not photos_of[i] & photos_of[j]:  # one person per photo
            parent[i] = j
            photos_of[j] |= photos_of[i]

    for first, then in _bursts(shots, list(on_photo)):
        for i, j in _same_people(people, on_photo[first], on_photo[then]):
            join(i, j)
    chains: dict[int, list[int]] = {}
    for i in range(len(people)):
        chains.setdefault(root(i), []).append(i)
    return [chain for chain in chains.values() if len(chain) > 1]


def _bursts(shots, photo_ids):
    """Pairs of the photos (``photo_ids``, in index order) one camera took at most
    BURST_SECONDS apart, in the order they were taken."""
    order = {photo_id: n for n, photo_id in enumerate(photo_ids)}
    timed = sorted(
        (shot[1], order[photo_id], shot[0], photo_id)
        for photo_id, shot in shots.items()
        if shot and photo_id in order
    )
    for x, (second, _, camera, first) in enumerate(timed):
        for later, _, other, then in timed[x + 1 :]:
            if later - second > BURST_SECONDS:
                break
            if other == camera:
                yield first, then


def _same_people(people, here, there):
    """Pairs of one person on two photos: each the other's best body match, alike
    enough and about in the same place."""
    likeness = np.array(
        [[people[i].body @ people[j].body for j in there] for i in here]
    )
    for row, i in enumerate(here):
        col = int(likeness[row].argmax())
        if (
            likeness[row, col] >= BURST_LIKENESS
            and int(likeness[:, col].argmax()) == row
            and _same_place(people[i].region, people[there[col]].region)
        ):
            yield i, there[col]


def _named(people, chains):
    """The bib a series holding exactly one names for each of its other people, by
    (photo id, region), as alike as they are to the nearest person known to wear it.
    A series with two bibs has picked up a second person somewhere and names nobody."""
    named: dict[tuple[str, str], tuple[str, float]] = {}
    for chain in chains:
        members = [people[i] for i in chain]
        known = [p for p in members if len(p.bibs) == 1]
        bibs = {p.bibs[0] for p in known}
        if len(bibs) != 1:
            continue
        (value,) = bibs
        for person in members:
            if not person.bibs:
                score = max(float(k.body @ person.body) for k in known)
                named[person.photo_id, person.region] = (value, score)
    return named


def _suggestion(value, score, region):
    return {
        "value": value,
        "method": "appearance",
        "state": "candidate",
        "confidence": float(np.clip(score, 0, 1)),
        "region": dict(zip(("x", "y", "w", "h"), region, strict=True)),
    }


def _blob(vector):
    return None if vector is None else vector.astype(np.float32).tobytes()


def _vector(blob):
    return None if blob is None else np.frombuffer(blob, dtype=np.float32)


def _face_table(references):
    """The references' faces as rows of one matrix, zeros where none shows, and which
    rows show one: a face is then compared with all of them in one product. None when
    no reference shows a face, so that faces decide nothing."""
    shown = np.array([f is not None for f in references], dtype=bool)
    if not shown.any():
        return None
    faces = np.stack([f for f in references if f is not None])
    table = np.zeros((len(references), faces.shape[1]), np.float32)
    table[shown] = faces
    return table, shown


def _likeness(known_faces, face):
    """Face similarity to each reference; -2 where the reference shows no face."""
    table, shown = known_faces
    return np.where(shown, table @ face, -2.0)


def _best(scores, values, owners, photo_id, taken):
    """The bib whose reference matches best, and its lead over the next bib.

    A reference on the same photo is another person, never this one, and so is a bib
    ``taken`` there already: the lead is over the bibs this rider can still wear.
    """
    best: dict[str, float] = {}
    for score, value, owner in zip(scores, values, owners, strict=True):
        if owner != photo_id and value not in taken and score > best.get(value, -2.0):
            best[value] = float(score)
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    if not ranked:
        return None, -1.0, 0.0
    second = ranked[1][1] if len(ranked) > 1 else -1.0
    return ranked[0][0], ranked[0][1], ranked[0][1] - second


def _matches(body, likeness, values, owners, photo_id, taken):
    """A face and the body agree on one bib, or the body alone is sure and well
    ahead of any other bib; ``likeness`` is None without faces. On the labelled races
    this found more people, at awards too, and suggested fewer wrong bibs than every
    bib above the body's threshold, which gave riders in one team's kit each other's
    bibs (the Sokol race)."""
    value, score, lead = _best(body, values, owners, photo_id, taken)
    if likeness is not None:
        known, face, _ = _best(likeness, values, owners, photo_id, taken)
        if known == value and face >= FACE_AGREES and score >= BODY_AGREES:
            return [(value, max(face, score))]
    if value is not None and score >= APPEARANCE_THRESHOLD and lead >= BODY_LEAD:
        return [(value, score)]
    return []


def _appearance(folder, index, engine, db, faces, progress, cancel, report):
    with _saved_once(folder, index, report):
        values, owners, seeds, references, named = _references(
            folder, index, engine, db, progress, cancel, report
        )
        known_faces = _face_table(references) if faces else None
        for n, photo in enumerate(index["photos"], 1):
            check_cancel(cancel)
            progress("Matching rider appearance", n, len(index["photos"]))
            if photo["processing_state"] == "failed":
                continue
            # Every photo, with suggestions or none: one changed since its references
            # stops the run, as one changed during OCR does.
            _verify(folder, photo)
            observations = []
            # Bibs accepted or typed here belong to someone else on the photo.
            taken = {
                b["value"]
                for b in photo["bibs"]
                if b["method"] == "manual" or b["state"] == "accepted"
            }
            crops = (
                db.execute(
                    "SELECT region, vector, face, known_bibs FROM crops"
                    " WHERE photo_id=?",
                    (photo["id"],),
                )
                if len(seeds)  # without references nothing can match
                else ()
            )
            for region, vector, face, known in crops:
                # A rider named only by a lone digit read by OCR gets suggestions too:
                # on the Sokol race they were as often right as the others.
                if _trusted(json.loads(known)):
                    continue
                if series := named.get((photo["id"], region)):
                    # The same person seconds before or after is surer than a likeness
                    # to another photo: one suggestion, not two different ones.
                    observations.append(_suggestion(*series, json.loads(region)))
                    continue
                scores = seeds @ np.frombuffer(vector, dtype=np.float32)
                query = _vector(face)
                likeness = (
                    None
                    if query is None or known_faces is None
                    else _likeness(known_faces, query)
                )
                matches = _matches(scores, likeness, values, owners, photo["id"], taken)
                for value, score in matches:
                    observations.append(_suggestion(value, score, json.loads(region)))
            _merge(photo, "appearance", observations)
            photo["processing_state"] = "processed"


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
