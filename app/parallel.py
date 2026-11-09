"""Bound read-only photo inference; the coordinator alone writes checkpoints."""

from __future__ import annotations

import multiprocessing
import os
import sys
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass

import psutil
from PIL import Image, ImageOps

from app import indexer
from app.model_cache import check_cancel
from app.vision import CpuVision


@dataclass(frozen=True)
class Plan:
    workers: int
    threads: int


def plan_for(photos: int, model_bytes: int = 0) -> Plan:
    try:
        cores = min(psutil.cpu_count(logical=False) or 1, os.process_cpu_count() or 1)
        # Reserve headroom for the UI/OS, roughly 1 GiB per decoded photo/task and
        # each worker's own copy of the models.
        memory = max(
            1, psutil.virtual_memory().available * 3 // 4 // (1024**3 + model_bytes)
        )
    except OSError, psutil.Error:
        return Plan(1, 1)
    workers = max(
        1, min(cores, memory, photos, 61 if sys.platform == "win32" else cores)
    )
    return Plan(workers, max(1, cores // workers))


class ChangedPhotoError(indexer.IndexError_):
    pass


def verify(folder, photo):
    path = folder / photo["original"]["path"]
    if indexer.sha256_of(path) != photo["original"]["sha256"]:
        raise ChangedPhotoError(
            f"{path.name} changed; rescan the folder before recognition"
        )
    return path


_engine = None


def _initialize(models, threads):
    global _engine
    _engine = CpuVision(models, threads=threads)


def infer(folder, photo, method, engine=None):
    """Return values or a per-photo I/O error, never mutate the photo or album."""
    try:
        indexer.check_decoder(folder / photo["original"]["path"])
        with Image.open(verify(folder, photo)) as source:
            with ImageOps.exif_transpose(source) as oriented:
                with oriented.convert("RGB") as image:
                    values = getattr(engine or _engine, method)(image)
        verify(folder, photo)
        return values, ""
    except (OSError, Image.DecompressionBombError) as exc:
        return [], str(exc)[:500]


def for_riders(models):
    """The models finding riders loads: none of those that read bibs."""
    return {
        key: path
        for key, path in models.items()
        if key not in ("text_detector", "text_reader")
        and not key.startswith("florence")
    }


class PhotoPool:
    def __init__(self, models, plan: Plan, riders: Plan | None = None):
        """``riders``, when given, plans finding riders in workers of their own that
        load only ``for_riders(models)``: lighter, so more of them fit in memory."""
        self._kinds = {"reading": (models, plan)}
        if riders:
            self._kinds["riders"] = (for_riders(models), riders)
        self._kind = "reading"
        self.plan = plan
        self.executor = self._start(models, plan)

    @staticmethod
    def _start(models, plan):
        return ProcessPoolExecutor(
            max_workers=plan.workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_initialize,
            initargs=(models, plan.threads),
        )

    def _use(self, kind):
        if kind != self._kind:
            # The reading workers' memory is freed before the lighter ones come.
            self.executor.shutdown(wait=True, cancel_futures=True)
            models, self.plan = self._kinds[kind]
            self.executor = self._start(models, self.plan)
            self._kind = kind
        return self.executor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def results(self, folder, photos, method, cancel):
        """At most one in-flight photo per worker; consume fast results first."""
        riders = method == "riders" and "riders" in self._kinds
        executor = self._use("riders" if riders else "reading")
        remaining = iter(photos)
        pending = {}

        def submit():
            check_cancel(cancel)
            if (photo := next(remaining, None)) is not None:
                pending[executor.submit(infer, folder, photo, method)] = photo

        try:
            for _ in range(self.plan.workers):
                submit()
            while pending:
                check_cancel(cancel)
                done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                for future in done:
                    check_cancel(cancel)
                    photo = pending.pop(future)
                    yield photo, future.result()
                    submit()
        except BaseException:
            # Children have no writable album state; stop them on cancel/fatal error.
            executor.terminate_workers()
            raise


def results(folder, photos, engine, method, cancel):
    if isinstance(engine, PhotoPool):
        yield from engine.results(folder, photos, method, cancel)
    else:
        for photo in photos:
            check_cancel(cancel)
            yield photo, infer(folder, photo, method, engine)


def _runtime_probe():
    import onnxruntime as ort

    ort.disable_telemetry_events()
    from pathlib import Path

    with Image.open(Path(__file__).with_name("codec_probe.heic")) as image:
        image.load()
        if image.size != (2, 2):
            raise RuntimeError("The HEIC decoder is missing")
    return (
        "CPUExecutionProvider" in ort.get_available_providers()
        and plan_for(1).workers == 1
    )


def check_runtime():
    """Exercise frozen spawn and native dependencies without downloading models."""
    pool = ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    )
    try:
        if not pool.submit(_runtime_probe).result(timeout=30):
            raise RuntimeError("The CPU recognition runtime is missing")
    except BaseException:
        pool.terminate_workers()
        raise
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
