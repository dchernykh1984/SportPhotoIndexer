# Parallel CPU recognition

## Policy

Use a bounded `ProcessPoolExecutor` with the `spawn` start method on every platform.
Each child loads the pinned models once and only reads originals. The coordinator
alone changes the manifest, applies manual-review rules and writes atomic checkpoints.
OCR finishes before the appearance pass collects its complete reference set. Both
OCR and rider detection/embedding extraction run across photos in parallel. The final
similarity comparison and checkpoint writes remain in the coordinator.

The initial budget is the smaller of physical cores and `os.process_cpu_count()`.
Hyperthreads do not count as additional physical cores. `psutil` supplies the physical
count and currently available RAM on macOS, Linux and Windows, including ARM64 wheels.
Missing resource information falls back to one worker and one model thread.

The photo-worker count is at most that budget, the number of photos, and 75% of
available RAM divided by a conservative 1 GiB allowance per worker. Windows also has
the standard-library limit of 61 process workers. The remaining CPU budget can go to
intra-operator threads when RAM or a small album limits photo workers:
`workers * model_threads <= core_budget`. Inter-operator parallelism stays sequential.
Idle model pools do not spin. The memory allowance is an estimate, not a hard RSS cap;
large decoded photos or other applications can change memory pressure after startup.

At most one photo is submitted per worker. Completed photos are saved immediately,
without waiting for an earlier slow photo. No decoded image is sent through a pipe:
children receive paths/metadata and return small OCR observations or body vectors.
Seed ordering follows the manifest, making equal-score suggestions independent of
completion order. SHA-256 checks before/after inference and again before publication
reject changed originals. A stale manifest stops the run rather than overwriting it.

Stop cancels the bounded queue and terminates the read-only children. Only completed,
saved OCR is resumed. Temporary appearance vectors are still removed on exit. Frozen
apps call `freeze_support()` before loading Qt; `--check-model-runtime` exercises a
spawned child and its native runtime, without needing downloaded models.

One task per core avoids oversubscription from this application. It cannot promise
absence of thermal throttling under sustained full load, or reserve CPU for other apps.

## Investigation

Initial comparison: 16 evenly spaced real race photos, on a Mac with 10 physical
cores (8 performance + 2 efficiency), 32 GiB RAM, Python 3.14.9 and ONNX Runtime
1.31.0. Each configuration starts its models and runs OCR plus body extraction on
the same files. No completed-OCR cache is used. Times include model/pool startup;
these preliminary measurements omit manifest writes and final similarity matching.

| Configuration | Seconds |
| --- | ---: |
| Previous serial photos, 4 model threads | 32.538 |
| Serial photos, 1 model thread | 52.486 |
| 4 photo threads, 1 model thread | 16.805 |
| 8 photo threads, 1 model thread | 12.147 |
| 4 photo processes, 1 model thread | 15.999 |
| 8 photo processes, 1 model thread | 9.604 |

All configurations returned the same per-photo observation/body counts. Processes
outperformed threads on this workload, which includes Python pixel/component loops.
The 8-process probe was 3.39 times faster than the previous serial configuration;
that is a measurement of this sample, not a guarantee for another CPU or album.

Full end-to-end comparison on all 158 photos, including model startup, original
SHA-256 checks, OCR, appearance matching, validation and manifest writes:

| Configuration | Seconds | Peak process-tree RSS |
| --- | ---: | ---: |
| Previous version, 1 photo / 4 model threads | 319.196 | 581 MiB |
| Automatic plan, 5 photos / 2 model threads each | 107.258 | 3052 MiB |

Available RAM at startup limited the automatic plan to five photo workers; their
two model threads still fit the ten-core budget. This run was **2.98 times faster**.
Both versions produced 30 appearance references and proposed bibs on 53 photos,
with no processing errors. Per-photo bib/method/state sets matched on every photo.
The measurements used separate temporary albums, without completed OCR checkpoints.
Original bytes were checked afterwards and remained unchanged. Pool startup is part
of the time, and the comparison is not a claim of identical speedup on other hardware.

HEIC decoding is supplied by `pillow-heif` with one decode thread; Pillow's AVIF
decoder is also limited to one thread. Camera formats always get separate JPEG
previews so neither Qt nor the site needs native HEIC support. The packaged runtime
probe decodes a tiny generated HEIC fixture in the spawned child. Multi-image HEIF
uses its primary image; GIF/TIFF use the first frame/page. Original files are read only.

## Primary references

- [ONNX Runtime thread management](https://onnxruntime.ai/docs/performance/tune-performance/threading.html):
  intra/inter-op pools, thread budgets and idle spinning.
- [Python concurrent futures](https://docs.python.org/3.14/library/concurrent.futures.html):
  bounded execution, cancellation, process limits and worker termination.
- [PyInstaller multiprocessing](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing):
  early `freeze_support()` and frozen spawn behaviour.
- [psutil CPU and memory APIs](https://psutil.readthedocs.io/stable/index.html):
  physical versus logical cores and available rather than merely free RAM.
- [psutil distribution](https://pypi.org/project/psutil/): native Windows ARM64 wheels.
