"""services/doc_converter/converter/pdf.py — PDF-to-markdown conversion.

Digital-native PDFs are converted via docling (TableFormer for tables).
Scanned PDFs are first OCR'd via ocrmypdf (tesseract), then converted via docling.
All four dependencies (docling, pymupdf, ocrmypdf, tesseract) are optional;
the tool degrades gracefully with friendly error messages.

Caching is handled by the caller (main.py) -- this module always performs
the conversion when invoked.
"""
from __future__ import annotations

import os
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

# Force CPU mode for docling (torch/onnxruntime) and tesseract (via ocrmypdf) --
# hiding all CUDA devices avoids GPU init attempts/failures on machines where
# a GPU stack isn't set up for this environment. Set before those libraries
# are imported anywhere in this process or its ProcessPoolExecutor workers.
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Pre-load torch on the main thread. On Windows, c10.dll's DllMain can fail
# with WinError 1114 when first loaded from a daemon thread. This module is
# imported at process startup on the main thread, so the DLL is already
# initialised by the time a worker thread needs it.
try:
    import torch  # noqa: F401
except ImportError:
    pass

_PAGE_MARKER_RE = re.compile(r"<!-- Page (\d+) -->")
_PAGE_BREAK_SENTINEL = "\x00DAGI_PAGE_BREAK\x00"


def parse_page_spec(spec: str) -> set[int]:
    """Parse a page spec like '1-3,5,8-10' into a set of 1-indexed page numbers."""
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                start, end = int(bounds[0].strip()), int(bounds[1].strip())
            except ValueError:
                raise ValueError(f"Invalid page spec: '{spec}'")
            pages.update(range(start, end + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                raise ValueError(f"Invalid page spec: '{spec}'")
    return pages


_SCANNED_CHAR_THRESHOLD = 50
PDF_PARALLEL_MIN_PAGES = 8   # below this, single-process path -- not config-exposed


def is_scanned_pdf(pdf_path: Path, sample_pages: int = 3) -> bool:
    """Probe first N pages for extractable text. Returns True if scanned."""
    try:
        import fitz
    except ImportError:
        return False
    doc = fitz.open(str(pdf_path))
    pages_to_check = min(sample_pages, len(doc))
    total_chars = sum(len(doc[i].get_text()) for i in range(pages_to_check))
    doc.close()
    return total_chars < _SCANNED_CHAR_THRESHOLD


def _get_page_count(pdf_path: Path) -> int:
    """Return the page count of a PDF, or 0 if fitz is unavailable."""
    try:
        import fitz
    except ImportError:
        return 0
    doc = fitz.open(str(pdf_path))
    count = len(doc)
    doc.close()
    return count


def _estimate_worker_count(page_count: int) -> int:
    """Estimate a safe worker-process count from CPU count, free RAM, and page count.

    page_count // 4 caps workers -- each worker handles at least 4 pages, so
    conversion overhead (process spawn, per-worker docling load) stays worth it.
    """
    worker_ram_gb = float(os.environ.get("PDF_WORKER_RAM_GB", "4.0"))
    max_workers_env = os.environ.get("PDF_MAX_WORKERS")
    caps = [os.cpu_count() or 1, page_count // 4]

    try:
        import psutil
        available_bytes = psutil.virtual_memory().available
        caps.append(int(available_bytes // (worker_ram_gb * 1024**3)))
    except ImportError:
        pass

    if max_workers_env is not None:
        caps.append(int(max_workers_env))

    return max(1, min(caps))


def _renumber_markers(markdown: str, start_offset: int) -> str:
    """Rewrite a chunk's local <!-- Page N --> markers to global page numbers.

    A chunk's docling output numbers pages from 1 within whatever pages it was
    given. start_offset is the chunk's first page number in the original
    document (1-indexed), so local page 1 becomes start_offset.
    """
    def _replace(match: re.Match) -> str:
        local = int(match.group(1))
        return f"<!-- Page {local + start_offset - 1} -->"

    return _PAGE_MARKER_RE.sub(_replace, markdown)


class ChunkSpec(NamedTuple):
    """One page-range chunk of a PDF being split for parallel conversion."""
    path: Path
    start_offset: int   # this chunk's first page number in the original doc (1-indexed)
    chunk_index: int    # 0-indexed position among sibling chunks, for reduce-step ordering


def _split_into_chunks(pdf_path: Path, cache_dir: Path, worker_count: int) -> list[ChunkSpec]:
    """Split a PDF into worker_count page-range sub-PDFs, written into cache_dir."""
    import fitz

    src = fitz.open(str(pdf_path))
    total_pages = len(src)
    base, extra = divmod(total_pages, worker_count)

    chunks: list[ChunkSpec] = []
    start = 0
    for i in range(worker_count):
        size = base + (1 if i < extra else 0)
        if size == 0:
            continue
        end = start + size - 1  # inclusive, 0-indexed
        chunk_doc = fitz.open()
        chunk_doc.insert_pdf(src, from_page=start, to_page=end)
        chunk_path = cache_dir / f"{pdf_path.stem}_chunk{i}.pdf"
        chunk_doc.save(str(chunk_path))
        chunk_doc.close()
        chunks.append(ChunkSpec(path=chunk_path, start_offset=start + 1, chunk_index=i))
        start = end + 1

    src.close()
    return chunks


def _convert_chunk(
    chunk_path: Path, is_scanned: bool, start_offset: int, chunk_index: int, cache_dir: Path
) -> tuple[int, str]:
    """Convert one page-range chunk and renumber its markers to global page numbers.

    Top-level function (not a closure/method) -- this is the callable dispatched
    to ProcessPoolExecutor, which requires picklable targets.
    """
    if is_scanned:
        # jobs=1: this call already runs inside one of worker_count sibling
        # processes. ocrmypdf otherwise defaults its own internal page-level
        # parallelism to os.cpu_count(), which would oversubscribe CPU/RAM by
        # a factor of worker_count on top of the outer pool.
        markdown = _convert_pdf_scanned(chunk_path, cache_dir, jobs=1)
    else:
        markdown = _convert_pdf_digital(chunk_path)
    return chunk_index, _renumber_markers(markdown, start_offset)


def _convert_pdf_parallel(
    pdf_path: Path, cache_dir: Path, scanned: bool, page_count: int, worker_count: int
) -> str:
    """Split, convert, and merge a PDF's pages using a worker process pool.

    Any chunk failure cancels not-yet-started chunks and propagates the error
    -- already-running chunks finish but their output is discarded. No partial
    markdown is ever returned. Temp chunk PDFs are always cleaned up.
    """
    chunks = _split_into_chunks(pdf_path, cache_dir, worker_count)
    results: dict[int, str] = {}
    try:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _convert_chunk, chunk.path, scanned, chunk.start_offset,
                    chunk.chunk_index, cache_dir,
                ): chunk
                for chunk in chunks
            }
            try:
                for future in as_completed(futures):
                    idx, markdown = future.result()
                    results[idx] = markdown
            except Exception:
                for future in futures:
                    future.cancel()
                raise
    finally:
        for chunk in chunks:
            chunk.path.unlink(missing_ok=True)

    return "".join(results[i] for i in sorted(results))


def _convert_pdf_digital(pdf_path: Path) -> str:
    """Convert a digital-native PDF to markdown via docling.

    OCR is explicitly disabled -- the caller has already established (via
    is_scanned_pdf) that this PDF has an extractable text layer. docling's
    default pipeline runs OCR unconditionally otherwise, loading the full
    RapidOCR/onnxruntime/torch stack per call. Under the parallel conversion
    path that means every worker process pays that cost concurrently, which
    has caused memory-exhaustion failures (WinError 1114 DLL init errors,
    std::bad_alloc) on machines with limited RAM.
    """
    try:
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            AcceleratorDevice,
            AcceleratorOptions,
            PdfPipelineOptions,
        )
    except ModuleNotFoundError as e:
        # e.name is the dotted module that was actually missing. A name
        # rooted at "docling" means the package itself isn't installed; any
        # other name (torch, onnxruntime, rapidocr, ...) means docling *is*
        # installed but one of its transitive dependencies isn't -- a
        # different problem with a different fix, so don't conflate the two.
        if e.name == "docling" or (e.name or "").startswith("docling."):
            raise RuntimeError(
                "docling is not installed. Install it with: pip install docling"
            ) from e
        raise RuntimeError(
            f"docling is installed but a dependency failed to import ({e.name}): {e}"
        ) from e
    except ImportError as e:
        # Distinct from ModuleNotFoundError: the module exists on disk but
        # failed to load, e.g. "DLL load failed while importing
        # onnxruntime_pybind11_state" from a broken native extension. This is
        # an environment problem, not a missing package -- surface the real
        # error instead of telling the user to (redundantly) pip install docling.
        raise RuntimeError(
            f"docling is installed but a dependency failed to import: {e}"
        ) from e
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = False
    # Force CPU inference explicitly -- belt-and-braces alongside the
    # CUDA_VISIBLE_DEVICES="" set at module import time above.
    pipeline_options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
    )
    result = converter.convert(str(pdf_path))
    # docling's page_break_placeholder is a flat separator with no page numbers of its
    # own -- split on a sentinel unlikely to occur in real content, then number each
    # page ourselves. Numbering restarts at 1 per call; _renumber_markers() shifts a
    # chunk's local numbers to global ones under the parallel conversion path.
    raw = result.document.export_to_markdown(page_break_placeholder=_PAGE_BREAK_SENTINEL)
    pages = raw.split(_PAGE_BREAK_SENTINEL)
    return "".join(f"<!-- Page {i} -->\n\n{page.strip()}\n\n" for i, page in enumerate(pages, start=1))


def _convert_pdf_scanned(pdf_path: Path, cache_dir: Path, jobs: int | None = None) -> str:
    """OCR a scanned PDF via ocrmypdf, then convert via docling.

    jobs caps ocrmypdf's own internal page-level worker count. Left at None
    for the single-process path (ocrmypdf defaults to os.cpu_count()). Callers
    running inside an already-parallel worker (_convert_chunk) must pass
    jobs=1, or ocrmypdf's default sizing oversubscribes CPU/RAM on top of the
    outer worker pool.
    """
    try:
        import ocrmypdf
    except ImportError:
        return _convert_pdf_digital(pdf_path)

    searchable_path = cache_dir / f"{pdf_path.stem}_ocr.pdf"
    try:
        ocrmypdf.ocr(
            str(pdf_path),
            str(searchable_path),
            skip_text=True,
            force_ocr=False,
            jobs=jobs,
        )
        return _convert_pdf_digital(searchable_path)
    finally:
        searchable_path.unlink(missing_ok=True)


def convert_pdf(pdf_path: Path) -> str:
    """Convert a PDF to markdown text. Returns the markdown string.

    The server-side cache is handled by the caller (main.py).
    This function always performs the conversion.
    """
    is_scanned = is_scanned_pdf(pdf_path)
    page_count = _get_page_count(pdf_path)

    if page_count > PDF_PARALLEL_MIN_PAGES:
        worker_count = _estimate_worker_count(page_count)
        if worker_count > 1:
            import tempfile
            cache_dir = Path(tempfile.mkdtemp(prefix="dagi_pdf_"))
            try:
                return _convert_pdf_parallel(
                    pdf_path, cache_dir, is_scanned,
                    page_count=page_count, worker_count=worker_count,
                )
            finally:
                import shutil
                shutil.rmtree(cache_dir, ignore_errors=True)

    if is_scanned:
        return _convert_pdf_scanned(pdf_path, pdf_path.parent)
    return _convert_pdf_digital(pdf_path)


def select_pages(markdown: str, pages_spec: str) -> str:
    """Filter cached markdown by page markers (<!-- Page N -->)."""
    requested = parse_page_spec(pages_spec)
    sections = re.split(r"(<!-- Page \d+ -->)", markdown)

    result_parts: list[str] = []
    current_page = 0
    for section in sections:
        page_match = re.match(r"<!-- Page (\d+) -->", section)
        if page_match:
            current_page = int(page_match.group(1))
            if current_page in requested:
                result_parts.append(section)
        elif current_page in requested:
            result_parts.append(section)

    return "".join(result_parts)
