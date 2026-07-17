# ReadTool PDF Support Design Spec

> **Date:** 2026-07-18 | **Status:** Draft | **Author:** Claude-chan + Admiral

---

## Goal

Extend `ReadTool` (`tools/read.py`) to convert `.pdf` files to line-numbered markdown, with
high-fidelity table extraction (merged cells, split cells, spanning headers) for both
digital-native and scanned PDFs. Converted output is cached on disk so repeat reads are instant.

## Why Not markitdown

The prior DOCX/XLSX/PPTX spec (2026-07-18) deliberately excluded PDF because `markitdown`'s
PDF backend uses `pdfplumber`/`pdfminer.six` layout heuristics — no OCR for scanned pages, and
complex tables collapse into run-on text with no recoverable row/column structure. This design
uses `docling` (IBM's deep-learning document converter with TableFormer) for conversion and
`ocrmypdf` + `tesseract` for scanned-page OCR, meeting a higher quality bar.

## Architecture

### Detection: Digital-Native vs. Scanned

Use `pymupdf` (fitz) to probe the first 3 pages of the PDF for extractable text:

```python
def _is_scanned_pdf(pdf_path: Path, sample_pages: int = 3) -> bool:
    import fitz
    doc = fitz.open(str(pdf_path))
    pages_to_check = min(sample_pages, len(doc))
    total_chars = sum(len(doc[i].get_text()) for i in range(pages_to_check))
    doc.close()
    return total_chars < 50
```

- **Threshold:** < 50 characters across sampled pages = scanned. Digital-native PDFs have
  hundreds of characters per page. The threshold is deliberately low to avoid false positives
  (e.g. a scanned cover page with a digital body).
- **Fallback if pymupdf not installed:** Skip detection, go straight to docling. Scanned PDFs
  will produce poor results but won't crash. Warning message advises installing pymupdf +
  ocrmypdf.

### Conversion Pipelines

#### Digital-Native Path

```python
def _convert_pdf_digital(pdf_path: Path) -> str:
    from docling.document_converter import DocumentConverter
    converter = DocumentConverter()
    result = converter.convert(str(pdf_path))
    md = result.document.export_to_markdown()
    return _inject_page_markers(result.document, md)
```

`_inject_page_markers()` iterates over the `DoclingDocument`'s elements (which track page
provenance) and inserts `<!-- Page N -->` comment markers at page boundaries. This is
necessary because `export_to_markdown()` does not natively include page separators.

Docling's `DocumentConverter` handles:
- Text extraction with reading order
- Table detection via TableFormer (deep learning) — handles merged cells, split cells, spanning headers
- Figure captions
- Multi-column layouts

#### Scanned Path

```python
def _convert_pdf_scanned(pdf_path: Path, cache_dir: Path) -> str:
    import ocrmypdf

    searchable_path = cache_dir / f"{pdf_path.stem}_ocr.pdf"
    ocrmypdf.ocr(
        str(pdf_path),
        str(searchable_path),
        skip_text=True,
        force_ocr=False,
    )

    md_text = _convert_pdf_digital(searchable_path)
    searchable_path.unlink(missing_ok=True)
    return md_text
```

1. `ocrmypdf` calls tesseract, identifies text with x,y bounding boxes, and injects an
   invisible text layer at the correct coordinates — producing a "searchable PDF."
2. The searchable PDF is then passed through the same docling pipeline as digital-native PDFs.
3. The intermediate searchable PDF is cleaned up after conversion.

`skip_text=True` ensures ocrmypdf won't re-OCR pages that already have an embedded text layer,
handling hybrid PDFs (some pages scanned, some digital) gracefully.

### Conversion Cache

#### Structure

```
.dagi/
└── pdf_cache/
    ├── a1b2c3d4e5f6...7890.md    <- SHA-256 of report.pdf content
    ├── f9e8d7c6b5a4...1234.md    <- SHA-256 of spec.pdf content
    └── ...
```

#### Flow

```python
_PDF_CACHE_DIR = ".dagi/pdf_cache"

def _get_pdf_cache_path(pdf_path: Path, project_root: Path) -> tuple[Path, str]:
    import hashlib
    content_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    cache_dir = project_root / _PDF_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / f"{content_hash}.md", content_hash

def _convert_pdf(pdf_path: Path, project_root: Path) -> tuple[str, Path]:
    cache_path, _ = _get_pdf_cache_path(pdf_path, project_root)

    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8"), cache_path

    if _is_scanned_pdf(pdf_path):
        md_text = _convert_pdf_scanned(pdf_path, cache_path.parent)
    else:
        md_text = _convert_pdf_digital(pdf_path)

    cache_path.write_text(md_text, encoding="utf-8", newline="\n")
    return md_text, cache_path
```

**Design decisions:**
- **Full SHA-256 in filename** — collision-proof, auto-invalidates when PDF content changes.
- **LF-only writes** (`newline="\n"`) — consistent with DAGI's EditTool/WriteTool convention.
- **Always cache the full document** — page-range requests slice from the cached markdown. A
  second read of different pages is still a cache hit.
- **Cache path in tool output** — the LLM sees where the cached `.md` lives and can reference
  it for copy/save operations on the user's behalf.
- **No cache eviction** — markdown files are small (KB). Manual cleanup if needed.

### Pages Parameter

New optional parameter added to ReadTool:

```python
"pages": {
    "type": "string",
    "description": (
        "Page range for PDF files (e.g. '1-5', '3', '10-12,15'). "
        "Only applicable to PDFs. Selects which pages of the converted "
        "markdown to return. Omit to return all pages."
    ),
}
```

#### Page Markers

During conversion, page markers are inserted into the markdown output:

```markdown
<!-- Page 1 -->
# Report Title

## Executive Summary
...

<!-- Page 2 -->
## Chapter 1
...
```

Docling tracks page provenance for every element. During `export_to_markdown()`, we iterate
page-by-page and insert `<!-- Page N -->` markers.

#### Filtering

```python
def _select_pages(markdown: str, pages_spec: str) -> str:
    requested = _parse_page_spec(pages_spec)  # -> set[int]
    sections = re.split(r'(<!-- Page \d+ -->)', markdown)

    result_parts = []
    current_page = 1
    for section in sections:
        page_match = re.match(r'<!-- Page (\d+) -->', section)
        if page_match:
            current_page = int(page_match.group(1))
            if current_page in requested:
                result_parts.append(section)
        elif current_page in requested:
            result_parts.append(section)

    return "".join(result_parts)
```

#### Order of Operations in `run()`

1. Full PDF -> markdown (or cache hit)
2. `pages` filter (if specified) -> subset of markdown
3. `offset`/`limit` on the resulting lines -> final windowed output
4. Line numbering -> return

### Tool Output Format

The output includes a metadata header before the line-numbered content:

```
[PDF: report.pdf | 23 pages | cached: .dagi/pdf_cache/a1b2c3d4.md | showing pages 1-5]
     1	# Report Title
     2	
     3	## Executive Summary
     4	...
```

The metadata line tells the LLM:
- The source file name
- Total page count
- Cache file path (for export/reference)
- Which pages are shown (if `pages` was specified)

## Dependencies

All dependencies are optional. The tool degrades gracefully based on what's installed.

| Dependency | Required For | Install | Type |
|---|---|---|---|
| `docling` | All PDF conversion | `pip install docling` | Python, lazy import |
| `pymupdf` (fitz) | Scanned-vs-digital detection | `pip install pymupdf` | Python, lazy import |
| `ocrmypdf` | Scanned PDF OCR overlay | `pip install ocrmypdf` | Python, lazy import |
| `tesseract` | OCR engine (used by ocrmypdf) | System package manager | System binary |

### Degradation Ladder

| State | Behavior |
|---|---|
| Everything installed | Full pipeline: detect, OCR if needed, docling, cache |
| docling only | Digital-native PDFs work. Scanned PDFs get a warning and attempt without OCR |
| pymupdf missing | Skip detection, go straight to docling. Warning if quality is poor |
| docling missing | Hard stop: `"Error: Could not convert 'report.pdf': docling is not installed. Install with: pip install docling"` |

### Docling Model Download

Docling's TableFormer models (~200-500MB) download automatically on first use (lazy download).
If offline, docling raises an error which is caught and surfaced as a friendly message. First
PDF read is slower (~30-60s download), subsequent reads use the downloaded model.

## Error Handling

All errors return a plain string (never a traceback), consistent with existing DOCX/XLSX/PPTX
error handling in ReadTool:

```python
# Missing core dependency
"Error: Could not convert 'report.pdf': docling is not installed. "
"Install with: pip install docling"

# Conversion failure
"Error: Could not convert 'report.pdf': <exception message>"

# Scanned PDF without OCR tools (warning, not error -- tries anyway)
"Warning: 'report.pdf' appears to be a scanned PDF but ocrmypdf is not installed. "
"Attempting conversion without OCR -- text extraction and table quality may be degraded. "
"For best results: pip install ocrmypdf && install tesseract"

# Pages parameter on non-PDF
"Error: 'pages' parameter is only supported for PDF files."
```

## Integration with Existing ReadTool

The new PDF path integrates into `ReadTool.run()` alongside the existing `_MARKITDOWN_EXTS`
branch (from the DOCX/XLSX/PPTX spec):

```python
def run(self, path: str, offset: int = 1, limit: int = 2000, pages: str | None = None) -> str:
    # ... path resolution, validation ...

    ext = p.suffix.lower()

    if pages is not None and ext != ".pdf":
        return "Error: 'pages' parameter is only supported for PDF files."

    if ext in _BLOCKED_EXTS:
        return "Error: Cannot read file type ..."

    if ext == ".pdf":
        # PDF pipeline: convert (or cache hit), filter pages, then fall through
        # to shared offset/limit + line numbering
        try:
            md_text, cache_path = _convert_pdf(p, self.cwd)
        except Exception as e:
            return f"Error: Could not convert '{p.name}': {e}"

        if pages:
            md_text = _select_pages(md_text, pages)

        lines = md_text.splitlines()
        total_pages = md_text.count("<!-- Page ")
        header = f"[PDF: {p.name} | {total_pages} pages | cached: {cache_path}"
        if pages:
            header += f" | showing pages {pages}"
        header += "]"

    elif ext in _MARKITDOWN_EXTS:
        # DOCX/XLSX/PPTX path (existing)
        ...
    else:
        # Text file path (existing)
        ...

    # Shared: offset/limit slicing + line numbering
    start = max(0, offset - 1)
    selected = lines[start : start + limit]
    numbered = "\n".join(f"{i:6d}\t{line}" for i, line in enumerate(selected, start + 1))

    if ext == ".pdf":
        return f"{header}\n{numbered}"
    return numbered
```

The PDF branch adds a metadata header before the numbered lines; all other branches return
numbered lines only (preserving existing behavior).

## Testing Strategy

Same approach as the DOCX/XLSX/PPTX tests — fake modules via `sys.modules` monkeypatch:

- **Mock `docling.document_converter.DocumentConverter`** with a fake that returns
  predetermined markdown (with `<!-- Page N -->` markers).
- **Mock `fitz` (pymupdf)** with a fake `open()` returning configurable text-per-page.
- **Mock `ocrmypdf.ocr`** with a no-op that copies the input file.
- **No real PDF fixtures needed** — tests exercise all code paths without binary files.

### Test Cases

1. Digital-native PDF returns line-numbered markdown
2. Scanned PDF routes through OCR then docling
3. Pages parameter filters output correctly (single page, range, comma-separated)
4. Pages parameter on non-PDF returns error
5. Offset/limit applied after pages filter
6. Cache hit returns same content without re-conversion
7. Cache invalidated when PDF content changes (different hash)
8. Missing docling returns friendly install error
9. Missing pymupdf skips detection, warns
10. Missing ocrmypdf on scanned PDF warns and attempts without OCR
11. Conversion exception returns friendly error (no traceback)
12. Text files unaffected by PDF branch
13. Metadata header includes cache path and page info

## Scope Exclusions

- **Cache eviction/cleanup** — deferred. Markdown files are small, manual cleanup suffices.
- **Password-protected PDFs** — not supported. Docling/pymupdf will raise; caught as a
  conversion error.
- **PDF form fields** — docling extracts visible text only, not form data.
- **Image extraction from PDFs** — out of scope. Text and tables only.
- **Concurrent conversion** — no locking on the cache. If two sessions convert the same PDF
  simultaneously, the last write wins (identical content, so no corruption).
