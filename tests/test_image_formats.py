"""Exercise real codecs, including HEIC, rather than renamed JPEG fixtures."""

import hashlib

import pytest
from PIL import AvifImagePlugin, Image
from pillow_heif import register_heif_opener

from app import indexer, parallel
from tests.test_recognition import FakeVision


@pytest.mark.parametrize(
    ("suffix", "format_", "mime"),
    [
        (".HEIC", "HEIF", "image/heic"),
        (".heif", "HEIF", "image/heif"),
        (".tiff", "TIFF", "image/tiff"),
        (".bmp", "BMP", "image/bmp"),
        (".gif", "GIF", "image/gif"),
        (".avif", "AVIF", "image/avif"),
    ],
)
def test_extra_photo_formats_keep_the_original_and_always_make_a_jpeg_preview(
    tmp_path, suffix, format_, mime
):
    if format_ == "AVIF" and not AvifImagePlugin.SUPPORTED:
        pytest.skip(
            "Pillow has no AVIF codec on Windows ARM64; HEIC is tested separately"
        )
    register_heif_opener(decode_threads=1)
    path = tmp_path / ("camera" + suffix)
    Image.new("RGB", (64, 48), "red").save(path, format=format_)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    data, report = indexer.scan(tmp_path)
    assert len(data["photos"]) == 1
    photo = data["photos"][0]
    assert photo["original"]["path"] == path.name
    assert photo["original"]["media_type"] == mime
    assert report.previews == 1
    preview = tmp_path / photo["preview"]["path"]
    with Image.open(preview) as image:
        assert image.format == "JPEG" and image.size == (64, 48)
        assert not image.getexif()
    readings, error = parallel.infer(tmp_path, photo, "ocr", FakeVision())
    assert not error and readings[0].value == "012"
    indexer.save(tmp_path, data)
    assert indexer.load(tmp_path)["photos"] == data["photos"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_the_frozen_decoder_probe_can_read_an_actual_heic():
    assert parallel._runtime_probe()


def test_an_unavailable_avif_decoder_is_reported_instead_of_dropping_the_photo(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(AvifImagePlugin, "SUPPORTED", False)
    path = tmp_path / "phone.avif"
    path.write_bytes(b"AVIF test input")
    assert path in indexer.photo_files(tmp_path)
    with pytest.raises(OSError, match="AVIF decoding is unavailable"):
        indexer.scan(tmp_path)
    photo = {"original": {"path": path.name, "sha256": indexer.sha256_of(path)}}
    readings, error = parallel.infer(tmp_path, photo, "ocr", FakeVision())
    assert not readings and "AVIF decoding is unavailable" in error


def test_rescanning_an_unchanged_heic_reuses_its_mandatory_preview(
    tmp_path, monkeypatch
):
    path = tmp_path / "phone.heic"
    Image.new("RGB", (64, 48), "red").save(path, format="HEIF")
    data, _ = indexer.scan(tmp_path)
    indexer.save(tmp_path, data)

    def unexpected(*args):
        raise AssertionError("An unchanged camera photo should reuse its preview")

    monkeypatch.setattr(indexer, "_make_preview", unexpected)
    again, report = indexer.scan(tmp_path, data)
    assert again["photos"] == data["photos"] and report.previews == 0


def test_rescanning_repairs_a_modified_heic_preview_without_changing_its_original(
    tmp_path,
):
    path = tmp_path / "phone.heic"
    Image.new("RGB", (64, 48), "red").save(path, format="HEIF")
    data, _ = indexer.scan(tmp_path)
    indexer.save(tmp_path, data)
    photo = data["photos"][0]
    preview = tmp_path / photo["preview"]["path"]
    preview.write_bytes(b"broken cached preview")
    again, report = indexer.scan(tmp_path, data)
    assert report.previews == 1
    assert again["photos"][0]["id"] == photo["id"]
    assert indexer.sha256_of(path) == photo["original"]["sha256"]
    assert indexer.sha256_of(preview) == again["photos"][0]["preview"]["sha256"]
    with Image.open(preview) as image:
        assert image.format == "JPEG"


def test_heif_primary_image_is_used_in_preview_and_a_spawned_worker(
    tmp_path, monkeypatch
):
    from tests.test_parallel import initialize_fake
    from tests.test_recognition import run

    monkeypatch.setattr(parallel, "_initialize", initialize_fake)
    path = tmp_path / "primary.heic"
    Image.new("RGB", (64, 48), "blue").save(
        path,
        format="HEIF",
        save_all=True,
        append_images=[Image.new("RGB", (64, 48), "red")],
        primary_index=1,
    )
    data, _ = indexer.scan(tmp_path)
    indexer.save(tmp_path, data)
    with parallel.PhotoPool({}, parallel.Plan(2, 1)) as pool:
        report = run(tmp_path, data, pool, appearance=False)
    assert not report.errors
    assert indexer.bibs_of(data["photos"][0]) == ["012"]
    with Image.open(tmp_path / data["photos"][0]["preview"]["path"]) as preview:
        red, green, blue = preview.getpixel((10, 10))
        assert red > green and red > blue
