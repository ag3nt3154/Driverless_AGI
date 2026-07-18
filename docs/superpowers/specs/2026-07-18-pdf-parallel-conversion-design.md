# PDF Parallel Conversion (Map-Reduce) — Design

## Goal

Speed up `convert_pdf()` (`tools/_pdf_convert.py`) for large PDFs by splitting the
document into page-range chunks, converting chunks in parallel across multiple
worker processes (docling for digital-native content, ocrmypdf→docling for
scanned content), then merging the per-chunk markdown back into a single
document — identical in shape to today's single-process output.

This is a pure performance optimization to the existing PDF pipeline shipped in
`2026-07-18-read-tool-pdf-support-design.md`. It does not change the cache
format, `select_pages()`, `ReadTool.run()`, or any public behavior — only how
fast large PDFs convert.

## Why map-reduce (not just a bigger threshold, not GPU batching, etc.)

- docling conversion is CPU/model-bound per page range; there's no batching API
  to hand it "convert these N disjoint chunks faster" — parallel processes are
  the straightforward lever.
- Threads were considered and rejected: docling's underlying torch/C++ work may
  or may not release the GIL, so a thread pool's speedup is unverified. A
  process pool guarantees true parallelism at the cost of one docling model
  load per worker process.

## Architecture

### 1. Detection (unchanged)

`is_scanned_pdf()` runs once on the whole document, exactly as today, to pick
the scanned-vs-digital pipeline. This is a single whole-document decision —
chunks never get mixed pipelines.

### 2. Decide whether to parallelize

```python
PDF_PARALLEL_MIN_PAGES = 8   # below this, single-process path (today's behavior)
PDF_WORKER_RAM_GB = 2.0      # conservative assumed RAM cost per docling worker
```

If `page_count <= PDF_PARALLEL_MIN_PAGES`, conversion stays single-process
(today's `_convert_pdf_digital`/`_convert_pdf_scanned` path, unchanged) — pool
startup and per-worker model-load overhead isn't worth it for short documents.

### 3. Estimate worker count

```python
worker_count = min(
    os.cpu_count(),
    psutil.virtual_memory().available // (PDF_WORKER_RAM_GB * 1024**3),
    num_chunks,
)
```

`psutil.virtual_memory().available` is **free/available memory, not total
installed RAM** — it already accounts for what other processes currently hold,
so the estimate doesn't oversubscribe a machine already under memory pressure.
`psutil` is added as a **core** (non-optional) dependency in `requirements.txt`
— it was already an undeclared transitive dependency used by
`tests/conftest.py`'s RAM-guard fixture; this feature makes it a real runtime
dependency of the PDF path too.

If `worker_count <= 1` (e.g. very low free RAM, or `os.cpu_count() == 1`),
conversion falls back to the single-process path even for large documents.

### 4. Map — split into chunks

Splitting uses `fitz` (pymupdf), already a declared optional dependency used
for scan detection. Pages are divided as evenly as possible across
`worker_count` chunks (e.g. 22 pages / 4 workers → chunks of 6, 6, 5, 5). Each
chunk is materialized as a standalone sub-PDF via
`fitz.open() + insert_pdf(src, from_page=..., to_page=...)`, written to a temp
file in the same cache-dir temp location `_convert_pdf_scanned` already uses.

Each chunk is dispatched to a `concurrent.futures.ProcessPoolExecutor` (pool
size = `worker_count`) as `(chunk_path, is_scanned, start_page_offset,
chunk_index)`. The function passed to the executor must be a picklable
top-level function (not a closure/method) — standard `ProcessPoolExecutor`
constraint. Each worker runs the existing per-chunk logic
(`_convert_pdf_scanned`/`_convert_pdf_digital`) unchanged, so OCR-if-scanned
happens inside the worker, and returns `(chunk_index, markdown)`. docling's
model loads lazily on a worker's first chunk and stays warm in that worker
process for any further chunks it's assigned (no eager pool initializer
needed).

### 5. Reduce — renumber and merge

1. Collect `(chunk_index, markdown)` futures; sort by `chunk_index` to restore
   original document order (executor completion order is not guaranteed).
2. Each chunk's `<!-- Page N -->` markers are *local* to that chunk (docling
   numbers from 1 within whatever it was given). Rewrite them to global page
   numbers using each chunk's recorded `start_page_offset`:
   `global = local + start_page_offset - 1`, via the same marker regex already
   used in `select_pages()`.
3. Concatenate renumbered chunk markdowns in order into one string —
   byte-for-byte equivalent in *shape* to a single-process conversion, so
   `select_pages()`, the cache layer, and `read.py`'s offset/limit logic need
   zero changes.
4. Clean up all temp chunk PDFs (and any OCR intermediates workers created) in
   a `finally` block, mirroring `_convert_pdf_scanned`'s existing cleanup
   pattern.

### 6. Failure handling

If any worker raises, cancel remaining futures and propagate the error out of
`convert_pdf()` — the whole conversion fails, exactly like a single-process
failure would today. No partial/incomplete markdown is ever written to cache.

## Integration point

```python
def convert_pdf(pdf_path: Path, project_root: Path) -> tuple[str, Path]:
    key = pdf_path.read_bytes()

    def compute() -> str:
        cache_dir = cache_path(key, "pdf", "md", project_root)[0].parent
        scanned = is_scanned_pdf(pdf_path)
        page_count = _get_page_count(pdf_path)  # new tiny fitz helper
        worker_count = (
            _estimate_worker_count(page_count)
            if page_count > PDF_PARALLEL_MIN_PAGES
            else 1
        )
        if worker_count <= 1:
            return (
                _convert_pdf_scanned(pdf_path, cache_dir)
                if scanned
                else _convert_pdf_digital(pdf_path)
            )
        return _convert_pdf_parallel(
            pdf_path, cache_dir, scanned, page_count, worker_count
        )

    return get_or_compute(key, "pdf", "md", project_root, compute)
```

New functions in `tools/_pdf_convert.py`:
- `_get_page_count(pdf_path: Path) -> int`
- `_estimate_worker_count(page_count: int) -> int`
- `_split_into_chunks(pdf_path: Path, cache_dir: Path, worker_count: int) -> list[ChunkSpec]`
- `_convert_chunk(chunk_path: Path, is_scanned: bool, start_offset: int, chunk_index: int) -> tuple[int, str]` (top-level, picklable — the executor target)
- `_renumber_markers(markdown: str, start_offset: int) -> str`
- `_convert_pdf_parallel(pdf_path: Path, cache_dir: Path, scanned: bool, page_count: int, worker_count: int) -> str` (orchestrator: split → dispatch → reduce → cleanup)

## Dependencies

| Dependency | Status | Used for |
|---|---|---|
| `psutil` | **New — core (required)** | Free-RAM estimate for worker count |
| `fitz` (pymupdf) | Existing optional | Scan detection (unchanged) + new: page-count lookup, chunk splitting |
| `docling` | Existing optional | Per-chunk conversion (unchanged, run per worker) |
| `ocrmypdf` | Existing optional | Per-chunk OCR (unchanged, run per worker) |

Parallel conversion requires `fitz` (for splitting) in addition to whatever the
chosen pipeline (`docling`/`ocrmypdf`) already required. If `fitz` is missing,
`is_scanned_pdf()` already returns `False` gracefully — page-count lookup for
the parallel-threshold check should degrade the same way (treat as unknown →
skip parallel path, single-process conversion as today).

## Testing strategy

Same `sys.modules` monkeypatch pattern as the rest of the PDF test suite: fake
`fitz`/`docling`/`ocrmypdf`/`psutil` modules. Tests must not spawn real OS
processes — `ProcessPoolExecutor` is patched/injected with a synchronous stub
executor (runs submitted callables immediately, in-process) so the suite stays
fast and deterministic.

New coverage:
- `_estimate_worker_count`: each of the three caps (cpu_count, free-RAM/2GB,
  num_chunks) binding in turn.
- `_split_into_chunks`: even split math, remainder distribution across
  workers.
- `_renumber_markers`: correctness of local→global page number rewriting.
- Small-doc fallback: `page_count <= PDF_PARALLEL_MIN_PAGES` always takes the
  single-process path (worker-count estimate never even computed).
- Failure propagation: one chunk's conversion raises → `convert_pdf()` raises,
  no cache file written.
- End-to-end: multi-chunk conversion output matches (byte-for-byte) what a
  stubbed single-process conversion of the same fake content would produce,
  proving the map-reduce path is shape-transparent to callers.

## Scope exclusions

- No `config.yaml` surface for worker count / RAM assumption — both are
  hardcoded constants in `tools/_pdf_convert.py`, tunable later if real-world
  numbers prove wrong.
- No per-chunk mixed pipelines — scan detection remains a single
  whole-document decision, applied uniformly to all chunks.
- No progress reporting mid-conversion — `convert_pdf()` remains a single
  blocking call from `read.py`'s perspective; parallelism is purely internal.
- No change to cache format, `select_pages()`, or `ReadTool.run()`.
- No cross-document parallelism (converting multiple different PDFs
  concurrently) — out of scope per the chosen "within one PDF" framing.
