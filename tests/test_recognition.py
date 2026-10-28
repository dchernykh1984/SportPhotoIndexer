"""Automatic recognition respects human decisions and checkpoints progress."""

from copy import deepcopy

import numpy as np
import pytest

from app import indexer, recognition
from app.vision import Reading, Rider
from tests.conftest import make_photo

BOX = (0.1, 0.1, 0.8, 0.8)
BIB_BOX = (0.3, 0.4, 0.1, 0.1)


class FakeVision:
    def __init__(self):
        self.calls = []
        self.readings = {0: [Reading("012", 0.99, BIB_BOX)]}
        self.crops = {
            0: [Rider(BOX, np.array([1.0, 0.0]))],
            1: [Rider(BOX, np.array([1.0, 0.0]))],
            2: [Rider(BOX, np.array([0.0, 1.0]))],
        }

    def _color(self, image):
        return int(np.asarray(image).mean(axis=(0, 1)).argmax())

    def ocr(self, image):
        color = self._color(image)
        self.calls.append(("ocr", color))
        return self.readings.get(color, [])

    def riders(self, image):
        color = self._color(image)
        self.calls.append(("riders", color))
        return self.crops[color]


def prepared(album):
    data, _ = indexer.scan(album)
    indexer.save(album, data)
    return data


def run(album, data, engine, **options):
    return recognition.run(
        album,
        data,
        engine,
        appearance=options.pop("appearance", True),
        progress=options.pop("progress", lambda *args: None),
        cancel=options.pop("cancel", lambda: False),
        size=options.pop("size", "small"),
        faces=options.pop("faces", False),
        starters=options.pop("starters", frozenset()),
    )


def test_bibs_run_first_and_seed_only_candidates_for_other_photos(album):
    data = prepared(album)
    engine = FakeVision()
    report = run(album, data, engine)
    assert [kind for kind, _ in engine.calls] == ["ocr"] * 3 + ["riders"] * 3
    assert report.seeds == 1 and report.errors == []
    first, second, third = data["photos"]
    assert indexer.bibs_of(first) == ["012"]
    assert second["bibs"][0]["value"] == "012"
    assert second["bibs"][0]["method"] == "appearance"
    assert second["bibs"][0]["state"] == "candidate"
    assert third["bibs"] == []
    assert indexer.load(album)["processing"]["complete"] is True
    assert "vector" not in (album / indexer.INDEX_FILE).read_text()
    assert not list(album.glob("*.sqlite3"))


def test_numbers_only_never_detects_riders_or_runs_appearance(album):
    data = prepared(album)
    engine = FakeVision()
    run(album, data, engine, appearance=False)
    assert [kind for kind, _ in engine.calls] == ["ocr"] * 3
    assert data["photos"][1]["bibs"] == []


def test_relay_templates_keep_both_appearances_of_one_bib(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[2] = [Reading("012", 0.99, BIB_BOX)]
    engine.crops[1] = engine.crops[2]
    assert run(album, data, engine).seeds == 2
    assert data["photos"][1]["bibs"][0]["value"] == "012"


def test_overlapping_riders_do_not_seed_an_ambiguous_bib(album):
    data = prepared(album)
    engine = FakeVision()
    engine.crops[0] = engine.crops[0] * 2
    assert run(album, data, engine).seeds == 0
    assert data["photos"][1]["bibs"] == []


def test_manual_corrections_and_an_empty_review_survive_reruns(album):
    data = prepared(album)
    red, green, blue = data["photos"]
    indexer.set_bibs(data, red["id"], ["012"])
    indexer.set_bibs(data, red["id"], ["045"])
    indexer.set_bibs(data, green["id"], [])
    indexer.save(album, data)
    engine = FakeVision()
    engine.readings[1] = [Reading("99", 0.99, BIB_BOX)]
    run(album, data, engine)
    assert indexer.bibs_of(red) == ["045"]
    assert not any(
        b["value"] == "012" and b["state"] != "rejected" for b in red["bibs"]
    )
    assert indexer.bibs_of(green) == []
    assert all(b["state"] == "candidate" for b in green["bibs"])
    assert green["manual_review"]["lock_accepted_set"] is True
    review_id = green["manual_review"]["review_id"]
    rerun = FakeVision()
    run(album, data, rerun)
    assert not any(kind == "ocr" for kind, _ in rerun.calls)
    assert green["manual_review"]["review_id"] == review_id
    assert indexer.bibs_of(blue) == []


def test_a_changed_original_drops_old_automatic_matches_and_archives_manual_review(
    album,
):
    data = prepared(album)
    photo = data["photos"][0]
    indexer.set_bibs(data, photo["id"], ["012"])
    old = deepcopy(photo["manual_review"])
    photo["bibs"].append({"value": "99", "method": "ocr", "state": "candidate"})
    indexer.save(album, data)
    make_photo(album, "IMG_0001.jpg", "black")
    updated, _ = indexer.scan(album, data)
    assert updated["photos"][0]["bibs"] == []
    assert "manual_review" not in updated["photos"][0]
    assert updated["photos"][0]["manual_history"][0]["review"] == old


def test_cancel_keeps_a_partial_checkpoint_and_resume_skips_completed_ocr(album):
    data = prepared(album)
    stopped = False

    def progress(phase, n, total):
        nonlocal stopped
        if n == 2:
            stopped = True

    report = run(album, data, FakeVision(), progress=progress, cancel=lambda: stopped)
    assert report.cancelled
    saved = indexer.load(album)
    assert not saved["processing"]["complete"]
    assert saved["photos"][0]["recognition"]["ocr"]["engine"] == recognition.engine_id()
    resumed = FakeVision()
    run(album, saved, resumed)
    assert [color for kind, color in resumed.calls if kind == "ocr"] == [1, 2]
    assert indexer.load(album)["processing"]["complete"]


def test_a_broken_photo_is_reported_without_losing_other_checkpoints(album):
    data = prepared(album)
    path = album / data["photos"][1]["original"]["path"]
    path.write_bytes(b"not a picture")
    data["photos"][1]["original"]["sha256"] = indexer.sha256_of(path)
    report = run(album, data, FakeVision())
    assert len(report.errors) == 1
    assert data["photos"][1]["processing_state"] == "failed"
    assert data["photos"][0]["processing_state"] == "processed"
    assert not indexer.load(album)["processing"]["complete"]


def test_concurrent_index_edits_are_never_overwritten(album):
    data = prepared(album)

    class Concurrent(FakeVision):
        def ocr(self, image):
            current = indexer.load(album)
            current["other-editor"] = True
            indexer.save(album, current)
            return super().ocr(image)

    with pytest.raises(indexer.StaleIndexError):
        run(album, data, Concurrent())
    saved = indexer.load(album)
    assert saved["other-editor"] is True
    assert all(p["bibs"] == [] for p in saved["photos"])


def test_a_photo_changed_during_inference_is_not_published(album):
    data = prepared(album)

    class Changing(FakeVision):
        def ocr(self, image):
            make_photo(album, "IMG_0001.jpg", "black")
            return super().ocr(image)

    with pytest.raises(recognition.ChangedPhotoError):
        run(album, data, Changing())
    assert indexer.load(album)["photos"][0]["bibs"] == []


def test_appearance_respects_the_bib_already_known_for_the_same_rider_crop(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[2] = [Reading("99", 0.99, BIB_BOX)]
    engine.crops[2] = engine.crops[0]  # different bibs, visually indistinguishable kit
    run(album, data, engine)
    red, green, blue = data["photos"]
    assert {b["value"] for b in red["bibs"]} == {"012"}
    assert {b["value"] for b in blue["bibs"]} == {"99"}
    assert {b["value"] for b in green["bibs"]} == {"012", "99"}
    assert all(b["state"] == "candidate" for b in green["bibs"])


def test_a_matching_face_lets_a_weaker_body_match_through(album):
    data = prepared(album)
    engine = FakeVision()
    face = np.array([0.0, 1.0])
    engine.crops[0] = [Rider(BOX, np.array([1.0, 0.0]), face)]
    # Changed clothes: the body is only 0.7 alike, the face is the same.
    engine.crops[1] = [Rider(BOX, np.array([0.7, np.sqrt(0.51)]), face)]
    engine.crops[2] = [Rider(BOX, np.array([0.7, np.sqrt(0.51)]), -face)]
    run(album, data, engine)
    assert data["photos"][1]["bibs"] == []
    run(album, data, engine, faces=True)
    _, green, blue = data["photos"]
    assert [(b["value"], b["state"]) for b in green["bibs"]] == [("012", "candidate")]
    assert green["bibs"][0]["confidence"] == pytest.approx(1.0)
    assert blue["bibs"] == []  # another face


def test_with_faces_an_ambiguous_body_suggests_nobody(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[2] = [Reading("99", 0.99, BIB_BOX)]
    engine.crops[2] = engine.crops[0]  # different bibs, visually indistinguishable kit
    run(album, data, engine, faces=True)
    assert data["photos"][1]["bibs"] == []


def test_with_faces_a_sure_body_match_ahead_of_other_bibs_still_counts(album):
    data = prepared(album)
    run(album, data, FakeVision(), faces=True)  # nobody shows a face
    assert [b["value"] for b in data["photos"][1]["bibs"]] == ["012"]
    assert data["photos"][2]["bibs"] == []


def test_near_threshold_and_lone_digit_reads_stay_candidates_any_format_accepted(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [
        Reading("44", 0.94, BIB_BOX),
        Reading("12", 0.96, (0.6, 0.1, 0.05, 0.02)),
        Reading("4", 0.98, (0.1, 0.5, 0.05, 0.02)),
        Reading("7", 0.995, (0.6, 0.5, 0.05, 0.02)),
        Reading("A12", 0.97, (0.1, 0.1, 0.05, 0.02)),
    ]
    run(album, data, engine, appearance=False)
    states = {b["value"]: b["state"] for b in data["photos"][0]["bibs"]}
    assert states == {
        "44": "candidate",
        "12": "accepted",
        "4": "candidate",
        "7": "accepted",
        "A12": "accepted",
    }


def test_cached_ocr_reapplies_calibration_without_repeating_inference(
    album, monkeypatch
):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False)
    assert data["photos"][0]["bibs"][0]["state"] == "accepted"
    monkeypatch.setattr(recognition, "ACCEPT_OCR", 0.9999)
    cached = FakeVision()
    run(album, data, cached, appearance=False)
    assert cached.calls == []
    assert data["photos"][0]["bibs"][0]["state"] == "candidate"


def test_bibs_saved_by_one_model_size_are_read_again_by_another(album):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False)
    larger = FakeVision()
    run(album, data, larger, appearance=False, size="florence-2-base")
    assert [kind for kind, _ in larger.calls] == ["ocr"] * 3
    stamp = data["photos"][0]["recognition"]["ocr"]["engine"]
    assert stamp == recognition.engine_id("florence-2-base") != recognition.engine_id()


def test_a_bib_outside_the_start_protocol_is_rejected_until_the_protocol_goes(album):
    data = prepared(album)
    report = run(album, data, FakeVision(), starters=frozenset({"7"}))
    red, green, _ = data["photos"]
    assert [(b["value"], b["state"]) for b in red["bibs"]] == [("012", "rejected")]
    assert report.seeds == 0 and green["bibs"] == []
    cached = FakeVision()
    run(album, data, cached)
    assert [kind for kind, _ in cached.calls] == ["riders"] * 3  # no new reading
    assert indexer.bibs_of(red) == ["012"]
    assert green["bibs"][0]["value"] == "012"


def test_a_protocol_matches_bibs_whatever_their_leading_zeroes_and_case(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[1] = [Reading("A7", 0.99, BIB_BOX)]
    run(album, data, engine, appearance=False, starters=frozenset({"12", "a07"}))
    assert indexer.bibs_of(data["photos"][0]) == ["012"]
    assert indexer.bibs_of(data["photos"][1]) == ["A7"]


def test_a_bib_the_protocol_hid_is_not_rejected_by_the_person_checking_the_photo(
    album,
):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False, starters=frozenset({"7"}))
    red = data["photos"][0]
    indexer.set_bibs(data, red["id"], ["7"])
    indexer.save(album, data)
    assert [(b["value"], b["method"]) for b in red["bibs"]] == [("7", "manual")]
    run(album, data, FakeVision(), appearance=False, size="florence-2-base")
    assert ("012", "candidate") in [(b["value"], b["state"]) for b in red["bibs"]]


def test_a_numbers_only_run_drops_older_suggestions_outside_the_protocol(album):
    data = prepared(album)
    run(album, data, FakeVision())
    green = data["photos"][1]
    assert green["bibs"][0]["method"] == "appearance"
    run(album, data, FakeVision(), appearance=False, starters=frozenset({"7"}))
    assert green["bibs"] == []


def test_an_unavailable_cached_photo_does_not_abort_the_other_photos(album):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False)
    (album / data["photos"][1]["original"]["path"]).unlink()
    cached = FakeVision()
    report = run(album, data, cached, appearance=False)
    assert len(report.errors) == 1
    assert data["photos"][1]["processing_state"] == "failed"
    assert data["photos"][0]["processing_state"] == "processed"
    assert data["photos"][2]["processing_state"] == "processed"
    assert cached.calls == []


def test_stop_is_honored_while_checking_only_cached_photos(album):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False)
    stopped = False
    checked = []

    def progress(phase, n, total):
        nonlocal stopped
        checked.append(n)
        stopped = True

    report = run(
        album,
        data,
        FakeVision(),
        appearance=False,
        progress=progress,
        cancel=lambda: stopped,
    )
    assert report.cancelled
    assert checked == [1]
