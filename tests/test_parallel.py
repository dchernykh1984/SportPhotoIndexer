"""Bound CPU work and keep parallel inference separate from index writes."""

from types import SimpleNamespace

import pytest

from app import indexer, parallel
from tests.test_recognition import FakeVision, prepared, run


@pytest.mark.parametrize(
    ("physical", "allowed", "gib", "photos", "expected"),
    [
        (8, 16, 32, 100, (8, 1)),
        (8, 3, 32, 100, (3, 1)),
        (8, 16, 2, 100, (1, 8)),
        (8, 16, 32, 2, (2, 4)),
        (None, None, 32, 100, (1, 1)),
        (8, 16, 32, 0, (1, 8)),
    ],
)
def test_plan_respects_physical_cores_affinity_memory_and_photo_count(
    monkeypatch, physical, allowed, gib, photos, expected
):
    monkeypatch.setattr(parallel.psutil, "cpu_count", lambda **kw: physical)
    monkeypatch.setattr(parallel.os, "process_cpu_count", lambda: allowed)
    monkeypatch.setattr(
        parallel.psutil,
        "virtual_memory",
        lambda: SimpleNamespace(available=gib * 1024**3),
    )
    plan = parallel.plan_for(photos)
    assert (plan.workers, plan.threads) == expected


def test_unavailable_resource_information_falls_back_to_one_worker(monkeypatch):
    def denied(*args, **kwargs):
        raise OSError("not available")

    monkeypatch.setattr(parallel.psutil, "cpu_count", denied)
    monkeypatch.setattr(parallel.psutil, "virtual_memory", denied)
    assert parallel.plan_for(100) == parallel.Plan(1, 1)


def initialize_fake(models, threads):
    parallel._engine = FakeVision()


class SynchronizedVision(FakeVision):
    def __init__(self, barrier):
        super().__init__()
        self.barrier = barrier

    def ocr(self, image):
        if self._color(image) in (0, 1):
            self.barrier.wait(timeout=10)
        return super().ocr(image)


def initialize_synchronized(models, threads):
    parallel._engine = SynchronizedVision(models["barrier"])


def test_two_photos_are_in_flight_but_only_the_coordinator_writes(album, monkeypatch):
    import multiprocessing
    import os

    monkeypatch.setattr(parallel, "_initialize", initialize_synchronized)
    data = prepared(album)
    writers = []
    save = indexer.save

    def recording_save(*args):
        writers.append(os.getpid())
        return save(*args)

    monkeypatch.setattr(indexer, "save", recording_save)
    barrier = multiprocessing.get_context("spawn").Barrier(2)
    with parallel.PhotoPool({"barrier": barrier}, parallel.Plan(2, 1)) as pool:
        report = run(album, data, pool)
    assert not report.errors and indexer.load(album)["processing"]["complete"]
    assert writers and set(writers) == {os.getpid()}


class BlockedVision(FakeVision):
    def __init__(self, started):
        super().__init__()
        self.started = started

    def ocr(self, image):
        import time

        self.started.set()
        time.sleep(30)
        return super().ocr(image)


def initialize_blocked(models, threads):
    parallel._engine = BlockedVision(models["started"])


def test_stop_terminates_read_only_workers_without_losing_the_last_index(
    album, monkeypatch
):
    import multiprocessing
    import threading

    monkeypatch.setattr(parallel, "_initialize", initialize_blocked)
    data = prepared(album)
    before = indexer.load(album)
    started = multiprocessing.get_context("spawn").Event()
    cancel = threading.Event()
    reports = []

    def recognize():
        with parallel.PhotoPool({"started": started}, parallel.Plan(2, 1)) as pool:
            reports.append(run(album, data, pool, cancel=cancel.is_set))

    thread = threading.Thread(target=recognize)
    thread.start()
    try:
        assert started.wait(10)
    finally:
        cancel.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert reports[0].cancelled
    assert indexer.load(album) == before


def test_frozen_runtime_probe_also_exercises_spawn():
    parallel.check_runtime()


def test_spawned_inference_keeps_manual_decisions_and_matches_serial_results(
    album, monkeypatch
):
    from copy import deepcopy

    from app import indexer

    monkeypatch.setattr(parallel, "_initialize", initialize_fake)
    data = prepared(album)
    indexer.set_bibs(data, data["photos"][1]["id"], [])
    indexer.save(album, data)
    serial = deepcopy(data)
    run(album, serial, FakeVision())
    # Reopen the same revision rather than overwriting the serial checkpoint.
    current = indexer.load(album)
    for photo in current["photos"]:
        photo.pop("recognition", None)
    indexer.save(album, current)
    with parallel.PhotoPool({}, parallel.Plan(2, 1)) as pool:
        report = run(album, current, pool)
    assert report.errors == [] and report.seeds == 1
    assert current["photos"] == serial["photos"]
    assert indexer.load(album)["photos"] == serial["photos"]


def test_cpu_sessions_share_one_thread_budget_and_do_not_spin(monkeypatch):
    import onnxruntime as ort

    from app.vision import CpuVision

    options = []

    class Session:
        def __init__(self, path, **kwargs):
            options.append(kwargs["sess_options"])

        def get_modelmeta(self):
            return SimpleNamespace(custom_metadata_map={"character": "0\n1"})

    monkeypatch.setattr(ort, "InferenceSession", Session)
    CpuVision({"text_reader": "reader.onnx"}, threads=2)
    assert options[0].intra_op_num_threads == 2
    assert options[0].inter_op_num_threads == 1
    assert options[0].get_session_config_entry("session.intra_op.allow_spinning") == "0"
