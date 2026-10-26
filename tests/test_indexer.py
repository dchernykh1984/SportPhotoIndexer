"""Scanning a folder, typing bibs and writing an index the site accepts."""

from __future__ import annotations

import json

import pytest

from app import indexer
from app.index_format import INDEX_FILE, problems
from tests.conftest import make_photo


def _scan_and_save(folder, **kwargs):
    index, report = indexer.scan(folder, indexer.load(folder), **kwargs)
    indexer.save(folder, index)
    return index, report


def test_a_first_scan_writes_an_index_the_site_accepts(album):
    _, report = _scan_and_save(album)
    assert report.added == 3
    on_disk = json.loads((album / INDEX_FILE).read_text(encoding="utf-8"))
    assert problems(on_disk) == []
    assert on_disk["revision"] == 1
    assert on_disk["processing"] == {
        "inventory_complete": True,
        "complete": False,
        "total": 3,
        "processed": 0,
    }
    assert [p["processing_state"] for p in on_disk["photos"]] == ["pending"] * 3


def test_ids_survive_a_rescan_and_the_revision_moves_only_on_change(album):
    first, _ = _scan_and_save(album)
    second, _ = _scan_and_save(album)
    assert [p["id"] for p in first["photos"]] == [p["id"] for p in second["photos"]]
    assert indexer.load(album)["revision"] == 1
    make_photo(album, "IMG_0009.jpg")
    _scan_and_save(album)
    assert indexer.load(album)["revision"] == 2


def test_typed_bibs_are_manual_and_bound_to_the_photo_bytes(album):
    index, _ = _scan_and_save(album)
    photo = index["photos"][0]
    indexer.set_bibs(index, photo["id"], indexer.parse_bibs("012 45A"))
    indexer.save(album, index)
    saved = indexer.load(album)["photos"][0]
    assert saved["processing_state"] == "processed"
    assert [(b["value"], b["method"]) for b in saved["bibs"]] == [
        ("012", "manual"),
        ("45A", "manual"),
    ]
    assert {b["content_sha256"] for b in saved["bibs"]} == {saved["original"]["sha256"]}


def test_a_photo_checked_with_no_bib_counts_as_processed(album):
    index, _ = _scan_and_save(album)
    indexer.set_bibs(index, index["photos"][1]["id"], [])
    assert index["photos"][1]["bibs"] == []
    assert index["processing"]["processed"] == 1


def test_a_bib_left_out_by_the_person_is_kept_as_rejected(album):
    index, _ = _scan_and_save(album)
    photo = index["photos"][0]
    indexer.set_bibs(index, photo["id"], ["12", "7"])
    indexer.set_bibs(index, photo["id"], ["12"])
    assert [(b["value"], b["state"]) for b in photo["bibs"]] == [
        ("12", "accepted"),
        ("7", "rejected"),
    ]


def test_a_changed_photo_loses_its_typed_bibs(album):
    index, _ = _scan_and_save(album)
    indexer.set_bibs(index, index["photos"][0]["id"], ["12"])
    indexer.save(album, index)
    make_photo(album, "IMG_0001.jpg", "black")
    index, report = indexer.scan(album, indexer.load(album))
    assert report.changed == 1 and report.stale_bibs == 1
    assert index["photos"][0]["bibs"] == []
    assert index["photos"][0]["processing_state"] == "pending"


def test_a_vanished_photo_is_listed_as_removed_not_dropped(album):
    index, _ = _scan_and_save(album)
    gone = index["photos"][2]["id"]
    (album / "IMG_0003.jpg").unlink()
    index, report = _scan_and_save(album)
    assert report.removed == 1
    assert gone in index["removed_photo_ids"]
    assert problems(indexer.load(album)) == []


def test_only_root_images_are_photos(album):
    (album / "notes.txt").write_text("x")
    (album / ".hidden.jpg").write_bytes(b"x")
    sub = album / "sub"
    sub.mkdir()
    make_photo(sub, "IMG_9999.jpg")
    assert [p.name for p in indexer.photo_files(album)] == [
        "IMG_0001.jpg",
        "IMG_0002.jpg",
        "IMG_0003.jpg",
    ]


def test_previews_on_request_and_for_photos_dropbox_cannot_shrink(album, monkeypatch):
    index, report = indexer.scan(album, None, previews=True)
    assert report.previews == 3
    assert index["photos"][0]["preview"]["path"] == "_previews/IMG_0001.jpg.jpg"
    monkeypatch.setattr(indexer, "THUMBNAIL_LIMIT_BYTES", 0)
    index, report = indexer.scan(album, None)
    assert report.previews == 3


def test_a_bib_the_site_would_refuse_is_refused_when_typed():
    with pytest.raises(indexer.IndexError_, match="1 to 32"):
        indexer.parse_bibs("x" * 33)
    assert indexer.parse_bibs(" 12, 12;7 ") == ["12", "7"]


def test_an_index_the_site_would_refuse_is_never_written(album):
    index, _ = _scan_and_save(album)
    indexer.set_bibs(index, index["photos"][0]["id"], [str(n) for n in range(21)])
    with pytest.raises(indexer.IndexError_, match="at most 20"):
        indexer.save(album, index)
    assert indexer.load(album)["revision"] == 1


def test_a_csv_sets_bibs_and_names_unknown_files(album, tmp_path):
    index, _ = indexer.scan(album, None)
    table = tmp_path / "bibs.csv"
    table.write_text("file;bibs\nIMG_0001.jpg;12 7\nIMG_0404.jpg;5\n", encoding="utf-8")
    applied, unknown = indexer.import_csv(index, table)
    assert (applied, unknown) == (1, ["IMG_0404.jpg"])
    assert indexer.bibs_of(index["photos"][0]) == ["12", "7"]


def test_an_unreadable_index_is_reported_not_overwritten(album):
    (album / INDEX_FILE).write_text("{oops", encoding="utf-8")
    with pytest.raises(indexer.IndexError_):
        indexer.load(album)


def test_the_index_is_replaced_in_one_step(album, monkeypatch):
    index, _ = _scan_and_save(album)
    indexer.set_bibs(index, index["photos"][0]["id"], ["1"])

    def fail(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(indexer.Path, "replace", fail)
    with pytest.raises(OSError):
        indexer.save(album, index)
    assert indexer.load(album)["revision"] == 1
    assert [p.name for p in album.iterdir() if p.name.startswith(".photo-index-")] == []


def test_a_photo_that_comes_back_keeps_its_id(album, tmp_path):
    index, _ = _scan_and_save(album)
    original_id = index["photos"][2]["id"]
    kept = tmp_path / "kept.jpg"
    (album / "IMG_0003.jpg").rename(kept)
    index, _ = _scan_and_save(album)
    assert original_id in index["removed_photo_ids"]
    kept.rename(album / "IMG_0003.jpg")
    index, _ = _scan_and_save(album)
    assert index["photos"][2]["id"] == original_id
    assert original_id not in index["removed_photo_ids"]
    assert problems(indexer.load(album)) == []


def test_an_index_opened_before_someone_else_saved_is_refused(album):
    _scan_and_save(album)
    first, second = indexer.load(album), indexer.load(album)
    indexer.set_bibs(first, first["photos"][0]["id"], ["12"])
    indexer.save(album, first)
    indexer.set_bibs(second, second["photos"][1]["id"], ["7"])
    with pytest.raises(indexer.StaleIndexError):
        indexer.save(album, second)
    assert indexer.bibs_of(indexer.load(album)["photos"][0]) == ["12"]


def test_a_second_writer_waits_for_the_lock(album):
    _scan_and_save(album)
    (album / ".photo-index.lock").write_text("")
    index = indexer.load(album)
    indexer.set_bibs(index, index["photos"][0]["id"], ["1"])
    with pytest.raises(indexer.StaleIndexError, match="another program"):
        indexer.save(album, index)


def test_an_index_over_the_sites_byte_limit_is_not_written(album, monkeypatch):
    _scan_and_save(album)
    monkeypatch.setattr(indexer, "MAX_INDEX_BYTES", 500)
    index = indexer.load(album)
    indexer.set_bibs(index, index["photos"][0]["id"], ["1"])
    with pytest.raises(indexer.IndexError_, match="split the album"):
        indexer.save(album, index)
    assert indexer.load(album)["revision"] == 1


def test_a_replaced_photo_gets_a_new_preview(album):
    index, _ = indexer.scan(album, None, previews=True)
    indexer.save(album, index)
    old = index["photos"][0]["preview"]["sha256"]
    make_photo(album, "IMG_0001.jpg", "black")
    index, _ = indexer.scan(album, indexer.load(album))
    assert index["photos"][0]["preview"]["sha256"] != old


def test_same_named_photos_of_two_formats_get_their_own_previews(tmp_path):
    folder = tmp_path / "album"
    folder.mkdir()
    make_photo(folder, "same.jpg", "red")
    make_photo(folder, "same.png", "blue")
    index, _ = indexer.scan(folder, None, previews=True)
    paths = [p["preview"]["path"] for p in index["photos"]]
    assert len(set(paths)) == 2
    for photo in index["photos"]:
        assert (
            indexer.sha256_of(folder / photo["preview"]["path"])
            == photo["preview"]["sha256"]
        )
