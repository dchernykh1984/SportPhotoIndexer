"""Automatic recognition respects human decisions and checkpoints progress."""

from copy import deepcopy

import numpy as np
import pytest
from PIL import Image

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


ROW = (0.45, 0.405, 0.1, 0.11)  # right of BIB_BOX, one height, one row
BELOW = (0.3, 0.6, 0.1, 0.1)  # BIB_BOX's row moved down
BELOW_RIGHT = (0.45, 0.605, 0.1, 0.11)


@pytest.mark.parametrize(
    ("reads", "accepted"),
    [
        # A board: two pairs of following numbers.
        ([("053", BIB_BOX), ("054", ROW), ("073", BELOW), ("074", BELOW_RIGHT)], set()),
        # A podium: the steps 2 and 3.
        ([("2", BIB_BOX), ("3", ROW)], set()),
        # Two riders side by side with following bibs, longer or lone.
        ([("065", BIB_BOX), ("066", ROW)], {"065", "066"}),
        ([("4", BIB_BOX), ("5", ROW)], {"4", "5"}),
        # A start grid: following bibs in two rows, riders' width apart.
        (
            [
                ("11", (0.1, 0.3, 0.05, 0.1)),
                ("12", (0.4, 0.3, 0.05, 0.1)),
                ("21", (0.1, 0.5, 0.05, 0.1)),
                ("22", (0.4, 0.5, 0.05, 0.1)),
            ],
            {"11", "12", "21", "22"},
        ),
        # Three teammates in one row.
        (
            [("101", BIB_BOX), ("102", ROW), ("103", (0.6, 0.4, 0.1, 0.1))],
            {"101", "102", "103"},
        ),
        # The two halves of bib 12 read on their own, touching.
        ([("1", (0.3, 0.4, 0.05, 0.1)), ("2", (0.35, 0.4, 0.05, 0.1))], {"1", "2"}),
        # A podium's narrow steps with a gap of half their width, in a tall frame.
        ([("2", (0.3, 0.4, 0.04, 0.2)), ("3", (0.36, 0.4, 0.04, 0.2))], set()),
        # Riders 1, 2 and 3, or 2, 3 and 4, side by side on a start line.
        (
            [
                ("1", (0.1, 0.4, 0.03, 0.1)),
                ("2", (0.3, 0.4, 0.03, 0.1)),
                ("3", (0.5, 0.4, 0.03, 0.1)),
            ],
            {"1", "2", "3"},
        ),
        (
            [
                ("2", (0.1, 0.4, 0.03, 0.1)),
                ("3", (0.3, 0.4, 0.03, 0.1)),
                ("4", (0.5, 0.4, 0.03, 0.1)),
            ],
            {"2", "3", "4"},
        ),
        # Riders 2 and 3 on a start line among other riders, beside or between them.
        (
            [
                ("17", (0.1, 0.4, 0.05, 0.1)),
                ("2", (0.3, 0.4, 0.03, 0.1)),
                ("3", (0.5, 0.4, 0.03, 0.1)),
            ],
            {"17", "2", "3"},
        ),
        (
            [
                ("2", (0.1, 0.4, 0.03, 0.1)),
                ("24", (0.3, 0.4, 0.05, 0.1)),
                ("3", (0.5, 0.4, 0.03, 0.1)),
            ],
            {"2", "24", "3"},
        ),
        # A podium with the winner's 1 read between the steps 2 and 3.
        (
            [
                ("2", (0.1, 0.5, 0.05, 0.1)),
                ("1", (0.3, 0.45, 0.05, 0.1)),
                ("3", (0.5, 0.5, 0.05, 0.1)),
            ],
            set(),
        ),
        # Two teammates close together in front, two more far behind: no board.
        (
            [
                ("141", (0.05, 0.5, 0.1, 0.3)),
                ("142", (0.3, 0.5, 0.1, 0.3)),
                ("77", (0.6, 0.2, 0.03, 0.06)),
                ("78", (0.66, 0.2, 0.03, 0.06)),
            ],
            {"141", "142", "77", "78"},
        ),
        # A board's row 1, 2 and 3, close together.
        (
            [
                ("1", (0.3, 0.4, 0.05, 0.1)),
                ("2", (0.4, 0.4, 0.05, 0.1)),
                ("3", (0.5, 0.4, 0.05, 0.1)),
            ],
            set(),
        ),
        # A board's pair below each other, and three times taller: no row of print.
        (
            [("053", BIB_BOX), ("054", BELOW), ("073", (0.5, 0.1, 0.1, 0.3))],
            {"053", "054", "073"},
        ),
    ],
)
def test_numbers_printed_in_rows_are_not_accepted_as_bibs(album, reads, accepted):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading(value, 0.999, box) for value, box in reads]
    run(album, data, engine, appearance=False)
    assert set(indexer.bibs_of(data["photos"][0])) == accepted


def test_a_podium_stays_a_podium_on_a_rerun_with_a_padding_protocol(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("2", 0.999, BIB_BOX), Reading("3", 0.999, ROW)]
    padded = frozenset({"02", "03"})
    run(album, data, engine, appearance=False, starters=padded)
    run(album, data, engine, appearance=False, starters=padded)  # from saved reads
    assert {b["value"] for b in data["photos"][0]["bibs"]} == {"02", "03"}
    assert indexer.bibs_of(data["photos"][0]) == []


def test_a_rider_s_plate_keeps_its_bib_when_the_board_shows_the_same_number(album):
    data = prepared(album)
    engine = FakeVision()
    board = [("053", BIB_BOX), ("054", ROW), ("073", BELOW), ("074", BELOW_RIGHT)]
    plate = Reading("054", 0.99, (0.6, 0.75, 0.1, 0.2))
    engine.readings[0] = [*(Reading(v, 0.999, box) for v, box in board), plate]
    run(album, data, engine, appearance=False)
    assert indexer.bibs_of(data["photos"][0]) == ["054"]


BOARD = [("053", BIB_BOX), ("054", ROW), ("073", BELOW), ("074", BELOW_RIGHT)]


@pytest.mark.parametrize(
    ("reads", "accepted"),
    [
        # The plate's 054 takes the board's place among the saved reads.
        ([*BOARD, ("054", (0.6, 0.75, 0.1, 0.2), 0.99)], ["054"]),
        # 054 printed in both rows is saved once.
        ([("053", BIB_BOX), ("054", ROW), ("054", BELOW), ("055", BELOW_RIGHT)], []),
    ],
)
def test_a_board_held_back_once_stays_held_back_on_a_rerun(album, reads, accepted):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [
        Reading(r[0], r[2] if len(r) > 2 else 0.999, r[1]) for r in reads
    ]
    run(album, data, engine, appearance=False)
    assert indexer.bibs_of(data["photos"][0]) == accepted
    run(album, data, engine, appearance=False)  # from the saved reads
    assert indexer.bibs_of(data["photos"][0]) == accepted


def test_a_board_stays_held_back_when_a_protocol_drops_its_numbers_and_takes_them_back(
    album,
):
    data = prepared(album)
    engine = FakeVision()
    reads = [("053", BIB_BOX), ("054", ROW), ("054", BELOW), ("055", BELOW_RIGHT)]
    engine.readings[0] = [Reading(v, 0.999, box) for v, box in reads]
    run(album, data, engine, appearance=False)
    run(album, data, engine, appearance=False, starters=frozenset({"053"}))
    every = frozenset({"053", "054", "055"})
    run(album, data, engine, appearance=False, starters=every)  # from the saved reads
    assert indexer.bibs_of(data["photos"][0]) == []


def test_the_print_found_is_remembered_by_its_values_only(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading(v, 0.999, box) for v, box in BOARD]
    run(album, data, engine, appearance=False)
    printed = data["photos"][0]["recognition"]["printed"]
    assert sorted(printed) == ["053", "054", "073", "074"]


def test_a_weak_read_saved_before_is_accepted_once_the_threshold_lets_it_in(
    album, monkeypatch
):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("54", 0.9, BIB_BOX)]
    run(album, data, engine, appearance=False)
    assert indexer.bibs_of(data["photos"][0]) == []
    monkeypatch.setattr(recognition, "ACCEPT_OCR", 0.85)
    run(album, data, engine, appearance=False)  # from the saved reads
    assert indexer.bibs_of(data["photos"][0]) == ["54"]


SAME_SPOT = (0.31, 0.405, 0.09, 0.1)  # mostly inside BIB_BOX


@pytest.mark.parametrize(
    ("reads", "states"),
    [
        # One sticker read as 39 and, less surely, as 33: 33 is only offered.
        (
            [("39", 1.0, BIB_BOX), ("33", 0.97, SAME_SPOT)],
            {"39": "accepted", "33": "candidate"},
        ),
        # Too unsure to be accepted on its own: not offered either.
        (
            [("39", 1.0, BIB_BOX), ("33", 0.9, SAME_SPOT)],
            {"39": "accepted", "33": "rejected"},
        ),
        # Two stickers side by side, or one read as surely both ways: both stay.
        (
            [("39", 1.0, BIB_BOX), ("33", 0.97, ROW)],
            {"39": "accepted", "33": "accepted"},
        ),
        (
            [("39", 0.97, BIB_BOX), ("33", 0.97, SAME_SPOT)],
            {"39": "accepted", "33": "accepted"},
        ),
    ],
)
def test_the_less_sure_of_two_values_read_on_one_spot_is_not_accepted(
    album, reads, states
):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading(value, c, box) for value, c, box in reads]
    for _ in range(2):  # the second from the saved reads
        run(album, data, engine, appearance=False)
        photo = data["photos"][0]
        assert {b["value"]: b["state"] for b in photo["bibs"]} == states


def test_a_value_the_protocol_rejects_takes_no_spot_from_a_starter(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("58", 1.0, BIB_BOX), Reading("50", 0.97, SAME_SPOT)]
    run(album, data, engine, appearance=False, starters=frozenset({"50"}))
    assert indexer.bibs_of(data["photos"][0]) == ["50"]


def test_a_weak_misread_beside_a_bib_makes_no_podium(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("3", 0.999, BIB_BOX), Reading("4", 0.5, ROW)]
    run(album, data, engine, appearance=False)
    assert indexer.bibs_of(data["photos"][0]) == ["3"]


def test_a_rider_s_own_plate_of_another_size_stays_accepted_on_a_board(album):
    data = prepared(album)
    engine = FakeVision()
    board = [("053", BIB_BOX), ("054", ROW), ("073", BELOW), ("074", BELOW_RIGHT)]
    plate = Reading("41", 0.999, (0.6, 0.75, 0.1, 0.2))
    engine.readings[0] = [*(Reading(v, 0.999, box) for v, box in board), plate]
    run(album, data, engine, appearance=False)
    assert indexer.bibs_of(data["photos"][0]) == ["41"]


def test_a_rider_s_bib_keeps_its_place_beside_twenty_numbers_of_a_board(album):
    data = prepared(album)
    engine = FakeVision()
    board = [
        Reading(str(first + i), 0.999, (0.02 + 0.09 * i, y, 0.05, 0.05))
        for first, y in ((11, 0.1), (21, 0.2))
        for i in range(10)
    ]
    plate = Reading("54", 0.96, (0.4, 0.6, 0.1, 0.2))
    engine.readings[0] = [*board, plate]
    run(album, data, engine, appearance=False)
    assert len(data["photos"][0]["bibs"]) == 20
    assert indexer.bibs_of(data["photos"][0]) == ["54"]


def test_a_superscript_digit_in_an_edited_index_stops_no_rerun(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("3", 0.999, ROW)]
    run(album, data, engine, appearance=False)
    region = dict(zip(("x", "y", "w", "h"), BIB_BOX, strict=True))
    data["photos"][0]["bibs"].append(
        {
            "value": "\u00b2",
            "state": "accepted",
            "method": "ocr",
            "confidence": 0.999,
            "region": region,
        }
    )
    run(album, data, engine, appearance=False)  # from the saved reads
    assert set(indexer.bibs_of(data["photos"][0])) == {"\u00b2", "3"}


def test_riders_with_following_bibs_beside_a_board_stay_accepted(album):
    data = prepared(album)
    engine = FakeVision()
    riders = [("41", (0.05, 0.8, 0.05, 0.18)), ("42", (0.6, 0.8, 0.05, 0.18))]
    engine.readings[0] = [Reading(v, 0.999, box) for v, box in BOARD + riders]
    run(album, data, engine, appearance=False)
    assert set(indexer.bibs_of(data["photos"][0])) == {"41", "42"}


def test_a_lone_digit_read_seeds_nobody(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("7", 0.999, BIB_BOX)]
    assert run(album, data, engine).seeds == 0
    assert indexer.bibs_of(data["photos"][0]) == ["7"]
    assert data["photos"][1]["bibs"] == []


@pytest.mark.parametrize(("confidence", "accepted"), [(0.97, False), (0.999, True)])
def test_a_lone_digit_spelled_longer_by_the_protocol_is_judged_as_one(
    album, confidence, accepted
):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [Reading("7", confidence, BIB_BOX)]
    report = run(album, data, engine, starters=frozenset({"007"}))
    assert indexer.bibs_of(data["photos"][0]) == (["007"] if accepted else [])
    assert report.seeds == 0  # sure or not, a lone digit names nobody else


def test_a_rider_named_only_by_a_lone_digit_read_still_gets_a_suggestion(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[1] = [Reading("7", 0.999, BIB_BOX)]  # green wears red's kit
    run(album, data, engine)
    second = data["photos"][1]["bibs"]
    assert [(b["value"], b["state"], b["method"]) for b in second] == [
        ("7", "accepted", "ocr"),
        ("012", "candidate", "appearance"),
    ]


def test_a_teammate_beside_a_named_rider_is_suggested_a_bib_still_free(album):
    data = prepared(album)
    engine = FakeVision()
    left, right = (0.0, 0.1, 0.45, 0.8), (0.5, 0.1, 0.45, 0.8)
    plate, other = (0.1, 0.4, 0.1, 0.1), (0.6, 0.4, 0.1, 0.1)
    engine.readings[0] = [Reading("054", 0.99, plate), Reading("055", 0.99, other)]
    engine.readings[1] = [Reading("054", 0.99, plate)]
    engine.crops[0] = [
        Rider(left, np.array([1.0, 0.0])),
        Rider(right, np.array([0.8, 0.6])),
    ]
    # Rider B on the second photo looks most like 054, already named there.
    engine.crops[1] = [
        Rider(left, np.array([1.0, 0.0])),
        Rider(right, np.array([0.98, 0.199])),
    ]
    run(album, data, engine)
    second = data["photos"][1]["bibs"]
    assert [(b["value"], b["method"]) for b in second] == [
        ("054", "ocr"),
        ("055", "appearance"),
    ]


def test_a_rider_named_by_a_typed_lone_digit_gets_no_other_bib_suggested(album):
    data = prepared(album)
    indexer.set_bibs(data, data["photos"][1]["id"], ["7"])
    run(album, data, FakeVision())
    assert [b["value"] for b in data["photos"][1]["bibs"]] == ["7"]


def test_a_stray_lone_digit_beside_a_rider_s_bib_does_not_stop_it_seeding(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0].append(Reading("1", 0.999, (0.5, 0.6, 0.05, 0.1)))  # a logo
    assert run(album, data, engine).seeds == 1
    assert [b["value"] for b in data["photos"][1]["bibs"]] == ["012"]


def test_a_typed_lone_digit_still_seeds_the_same_rider_elsewhere(album):
    data = prepared(album)
    indexer.set_bibs(data, data["photos"][0]["id"], ["7"])
    indexer.save(album, data)
    assert run(album, data, FakeVision()).seeds == 1
    assert [b["value"] for b in data["photos"][1]["bibs"]] == ["7"]


def test_a_rider_with_two_bibs_in_the_box_seeds_nobody(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[0] = [
        Reading("012", 0.99, BIB_BOX),
        Reading("045", 0.99, (0.5, 0.6, 0.1, 0.1)),
    ]
    assert run(album, data, engine).seeds == 0
    assert indexer.bibs_of(data["photos"][0]) == ["012", "045"]
    assert data["photos"][1]["bibs"] == []


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


def saves_by_phase(monkeypatch):
    """The phase shown when each checkpoint was written."""
    phases, saves = [None], []
    real = recognition._checkpoint

    def counted(folder, index):
        saves.append(phases[-1])
        real(folder, index)

    monkeypatch.setattr(recognition, "_checkpoint", counted)
    return lambda phase, n, total: phases.append(phase), saves


def test_matching_rider_appearance_saves_the_index_once(album, monkeypatch):
    data = prepared(album)
    progress, saves = saves_by_phase(monkeypatch)
    run(album, data, FakeVision(), progress=progress)
    assert saves.count("Matching rider appearance") == 1
    assert indexer.load(album)["processing"]["complete"]


def test_checking_saved_bib_numbers_saves_the_index_once(album, monkeypatch):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False)
    progress, saves = saves_by_phase(monkeypatch)
    run(album, data, FakeVision(), appearance=False, progress=progress)
    assert saves == ["Checking saved bib numbers"]


def test_appearance_hashes_each_photo_once_where_its_bibs_are_written(
    album, monkeypatch
):
    data = prepared(album)
    phases, hashed = [None], []
    real = recognition._verify

    def counted(folder, photo):
        hashed.append(phases[-1])
        return real(folder, photo)

    monkeypatch.setattr(recognition, "_verify", counted)
    run(album, data, FakeVision(), progress=lambda p, n, t: phases.append(p))
    assert "Finding rider references" not in hashed
    assert hashed.count("Matching rider appearance") == len(data["photos"])


@pytest.mark.parametrize("name", ["IMG_0002.jpg", "IMG_0003.jpg"])
def test_a_photo_changed_after_its_references_stops_the_run(album, name):
    data = prepared(album)  # IMG_0002 gets a suggestion, IMG_0003 none

    def progress(phase, n, total):
        if phase == "Finding rider references" and n == total:
            make_photo(album, name, "black")

    with pytest.raises(recognition.ChangedPhotoError):
        run(album, data, FakeVision(), progress=progress)


def test_a_photo_changed_before_its_appearance_is_written_is_not_published(album):
    data = prepared(album)

    def progress(phase, n, total):
        if phase == "Matching rider appearance" and n == 1:
            make_photo(album, "IMG_0002.jpg", "black")

    with pytest.raises(recognition.ChangedPhotoError):
        run(album, data, FakeVision(), progress=progress)
    saved = indexer.load(album)["photos"][1]["bibs"]
    assert all(b["method"] != "appearance" for b in saved)


def test_a_face_is_compared_with_every_reference_in_one_product():
    rng = np.random.default_rng(0)
    faces = [rng.standard_normal(4).astype(np.float32) for _ in range(4)]
    references = [faces[0], None, faces[1], None, faces[2]]
    known_faces = recognition._face_table(references)
    expected = [-2.0 if f is None else float(f @ faces[3]) for f in references]
    assert np.allclose(recognition._likeness(known_faces, faces[3]), expected)
    assert recognition._face_table([None, None]) is None


def test_without_faces_no_face_table_is_built(album, monkeypatch):
    def refuse(references):
        raise AssertionError("faces are off")

    monkeypatch.setattr(recognition, "_face_table", refuse)
    run(album, prepared(album), FakeVision(), faces=False)


def test_stop_while_matching_keeps_the_photos_matched_so_far(album):
    data = prepared(album)
    stopped = False

    def progress(phase, n, total):
        nonlocal stopped
        stopped = phase == "Matching rider appearance" and n == 2

    report = run(album, data, FakeVision(), progress=progress, cancel=lambda: stopped)
    assert report.cancelled
    states = [p["processing_state"] for p in indexer.load(album)["photos"]]
    assert states == ["processed", "processed", "pending"]


def test_a_photo_failing_its_references_is_saved_with_the_pass(album, monkeypatch):
    data = prepared(album)

    class Unreadable(FakeVision):
        def riders(self, image):
            if self._color(image) == 1:
                raise OSError("unreadable")
            return super().riders(image)

    progress, saves = saves_by_phase(monkeypatch)
    run(album, data, Unreadable(), progress=progress)
    assert "Finding rider references" not in saves
    failed = indexer.load(album)["photos"][1]
    assert failed["processing_state"] == "failed"
    assert failed["recognition_error"] == "unreadable"


def test_stop_while_checking_saved_reads_keeps_what_was_checked(album):
    data = prepared(album)
    run(album, data, FakeVision(), appearance=False)
    (album / "IMG_0001.jpg").unlink()
    stopped = False

    def progress(phase, n, total):
        nonlocal stopped
        stopped = n == 2

    report = run(
        album,
        data,
        FakeVision(),
        appearance=False,
        progress=progress,
        cancel=lambda: stopped,
    )
    assert report.cancelled
    assert indexer.load(album)["photos"][0]["processing_state"] == "failed"


def test_a_stop_still_reads_as_a_stop_when_the_save_then_fails(album, monkeypatch):
    data = prepared(album)
    stopped = False

    def refuse(folder, index):
        raise indexer.StaleIndexError("changed elsewhere")

    def progress(phase, n, total):
        nonlocal stopped
        if phase == "Matching rider appearance" and n == 2:
            stopped = True
            monkeypatch.setattr(indexer, "save", refuse)  # saved elsewhere meanwhile

    report = run(album, data, FakeVision(), progress=progress, cancel=lambda: stopped)
    assert report.cancelled
    assert any("not saved: changed elsewhere" in e for e in report.errors)


def test_appearance_respects_the_bib_already_known_for_the_same_rider_crop(album):
    data = prepared(album)
    engine = FakeVision()
    engine.readings[2] = [Reading("99", 0.99, BIB_BOX)]
    engine.crops[2] = engine.crops[0]  # different bibs, visually indistinguishable kit
    run(album, data, engine)
    red, green, blue = data["photos"]
    assert {b["value"] for b in red["bibs"]} == {"012"}
    assert {b["value"] for b in blue["bibs"]} == {"99"}
    # Alike on the body, neither bib leads the other: green is given neither.
    assert green["bibs"] == []


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


def test_small_keeps_its_saved_bibs_and_florence_sizes_read_with_finer_windows():
    # The version, not the model hashes: those move whenever a model is re-pinned.
    assert recognition.engine_id().startswith("people-v2:")
    for size in ("florence-2-base-int8", "florence-2-base"):
        assert recognition.engine_id(size).startswith("people-v3:")


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
    # Saved as the protocol spells them: the site matches a starter's bib exactly.
    assert indexer.bibs_of(data["photos"][0]) == ["12"]
    assert indexer.bibs_of(data["photos"][1]) == ["a07"]


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


def test_a_numbers_only_run_keeps_suggestions_of_a_bib_a_person_typed(album):
    data = prepared(album)
    red, green, _ = data["photos"]
    indexer.set_bibs(data, red["id"], ["99"])  # a late entrant, not in the protocol
    indexer.save(album, data)
    run(album, data, FakeVision())
    assert [b["value"] for b in green["bibs"]] == ["99"]
    run(album, data, FakeVision(), appearance=False, starters=frozenset({"7"}))
    assert [b["value"] for b in green["bibs"]] == ["99"]


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


def taken(path, moment, camera="TEST Z 6"):
    """The photo as a camera saves it: its model and the moment it was taken."""
    with Image.open(path) as image:
        image.load()
    exif = Image.Exif()
    exif[272] = camera
    exif.get_ifd(0x8769)[36867] = moment
    image.save(path, exif=exif)


V0 = np.array([1.0, 0.0, 0.0])
V1 = np.array([0.7, 0.51**0.5, 0.0])  # 0.7 like V0: below APPEARANCE_THRESHOLD
V2 = np.array([0.55, 0.469, (1 - 0.55**2 - 0.469**2) ** 0.5])  # 0.72 like V1, 0.55 V0
MOVED = (0.85, 0.1, 0.1, 0.8)  # 0.4 of the width away from the middle of BOX


def series(
    album,
    moments,
    cameras=("TEST Z 6",) * 3,
    boxes=(BOX,) * 3,
    bibs=None,
    vectors=(V0, V1, V2),
):
    """Bib 12 read on the first photo; one rider on each, by default alike only to the
    next."""
    for path, moment, camera in zip(
        sorted(album.glob("*.jpg")), moments, cameras, strict=True
    ):
        if moment:
            taken(path, moment, camera)
    data = prepared(album)
    engine = FakeVision()
    engine.readings = {0: [Reading("12", 0.99, BIB_BOX)], **(bibs or {})}
    engine.crops = {
        n: [Rider(box, vector)]
        for n, (box, vector) in enumerate(zip(boxes, vectors, strict=True))
    }
    run(album, data, engine)
    return [
        {b["value"] for b in photo["bibs"] if b["method"] == "appearance"}
        for photo in data["photos"]
    ]


SECONDS = ("2026:11:08 10:00:00", "2026:11:08 10:00:02", "2026:11:08 10:00:04")


def test_a_bib_read_once_is_offered_along_a_series_of_one_camera(album):
    assert series(album, SECONDS) == [set(), {"12"}, {"12"}]


@pytest.mark.parametrize(
    "options",
    [
        # Ten seconds apart: no series.
        {
            "moments": (
                "2026:11:08 10:00:00",
                "2026:11:08 10:00:10",
                "2026:11:08 10:00:20",
            )
        },
        # Three cameras, or no time at all.
        {"moments": SECONDS, "cameras": ("A", "B", "C")},
        {"moments": (None, None, None)},
        # The rider seen across the photo, not where they stood.
        {"moments": SECONDS, "boxes": (BOX, MOVED, BOX)},
        # The series holds a second bib: it took in someone else.
        {"moments": SECONDS, "bibs": {2: [Reading("34", 0.99, BIB_BOX)]}},
    ],
)
def test_no_series_no_bib_offered(album, options):
    assert series(album, **options) == [set(), set(), set()]


def test_a_series_offers_its_bib_to_nobody_too_unlike_its_wearer(album):
    unlike = np.array([0.3, 0.7, (1 - 0.3**2 - 0.7**2) ** 0.5])  # 0.71 like V1
    assert series(album, SECONDS, vectors=(V0, V1, unlike)) == [set(), {"12"}, set()]


LEFT, RIGHT = (0.05, 0.1, 0.3, 0.8), (0.6, 0.1, 0.3, 0.8)


def test_a_series_reaching_a_photo_where_its_bib_is_worn_names_nobody(album):
    # The series takes a lookalike on the second photo, where 12 is read on another.
    for path, moment in zip(sorted(album.glob("*.jpg")), SECONDS, strict=True):
        taken(path, moment)
    data = prepared(album)
    engine = FakeVision()
    engine.readings = {
        0: [Reading("12", 0.99, (0.15, 0.4, 0.1, 0.1))],
        1: [Reading("12", 0.99, (0.7, 0.4, 0.1, 0.1))],
    }
    engine.crops = {
        0: [Rider(LEFT, V0)],
        1: [Rider(LEFT, V1), Rider(RIGHT, np.array([0.0, -0.6, 0.8]))],
        2: [Rider(LEFT, V2)],
    }
    run(album, data, engine)
    assert [
        {b["value"] for b in photo["bibs"] if b["method"] == "appearance"}
        for photo in data["photos"]
    ] == [set(), set(), set()]


def test_a_series_through_a_rider_with_other_bibs_names_nobody(album):
    # Two bibs, neither 12, read in the second photo's rider's box.
    two = [Reading("34", 0.99, BIB_BOX), Reading("56", 0.99, (0.5, 0.4, 0.1, 0.1))]
    assert series(album, SECONDS, bibs={1: two})[2] == set()


def test_a_person_a_series_names_gets_no_second_bib(album):
    # Photo 3, outside the series, shows bib 34 on someone just like photo 2's rider.
    moments = ("2026:11:08 10:00:00", "2026:11:08 10:00:02", "2026:11:08 10:00:15")
    bibs = {2: [Reading("34", 0.99, BIB_BOX)]}
    found = series(album, moments, bibs=bibs, vectors=(V0, V1, V1))
    assert found[1] == {"12"}


def test_one_person_is_never_twice_on_one_photo_in_a_series():
    q = np.array([1.0, 1.0, 0.0]) / 2**0.5
    p2 = np.array([0.0, 1.0, 0.3]) / 1.09**0.5
    region = "[0.1, 0.1, 0.3, 0.8]"
    people = [
        recognition._Person("A", region, np.array([1.0, 0.0, 0.0]), []),
        recognition._Person("A", region, p2, []),
        recognition._Person("B", region, q, []),
        recognition._Person("C", region, np.array([0.0, 1.0, 0.0]), []),
    ]
    shots = {"A": (("TEST", ""), 0), "B": (("TEST", ""), 1), "C": (("TEST", ""), 2)}
    # A's first person links to B, A's second to C; B and C alike would join them.
    chains = recognition._chains(people, shots)
    assert sorted(sorted(chain) for chain in chains) == [[0, 2], [1, 3]]


def test_a_photo_without_a_readable_time_has_none(tmp_path):
    (tmp_path / "notes.jpg").write_text("not a photo")
    make_photo(tmp_path, "plain.jpg")
    named = make_photo(tmp_path, "named.jpg")
    taken(named, "2026:11:08 10:00:02", "TEST Z 6")
    unset = make_photo(tmp_path, "unset.jpg")
    taken(unset, "0000:00:00 00:00:00", "TEST Z 6")
    model_only = make_photo(tmp_path, "model.jpg")
    with Image.open(model_only) as image:
        image.load()
    exif = Image.Exif()
    exif[272] = "TEST Z 6"
    image.save(model_only, exif=exif)
    assert recognition._shot(tmp_path / "notes.jpg") is None
    assert recognition._shot(tmp_path / "plain.jpg") is None
    assert recognition._shot(unset) is None
    assert recognition._shot(model_only) is None
    assert recognition._shot(named) == (("TEST Z 6", ""), 1794132002)
