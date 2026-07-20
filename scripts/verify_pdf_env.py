"""
scripts/verify_pdf_env.py — Eagerly import every PDF-conversion dependency.

docling, torch, onnxruntime, and rapidocr are all imported lazily by
tools/_pdf_convert.py, so a broken install (e.g. a missing Windows DLL) only
surfaces the first time someone reads a PDF, deep inside a worker process.
Run this right after `pip install -r requirements.txt` to catch that at
setup time instead, with a diagnosis attached.
"""
from __future__ import annotations

import importlib
import sys

# name -> module to import; order matters, since torch/onnxruntime failures
# are what docling's own import would otherwise surface indirectly.
_CHECKS = [
    ("pymupdf (fitz)", "fitz"),
    ("torch", "torch"),
    ("onnxruntime", "onnxruntime"),
    ("rapidocr", "rapidocr"),
    ("docling", "docling.document_converter"),
    ("ocrmypdf", "ocrmypdf"),
]

_WINDOWS_DLL_HINT = """
A "DLL load failed" / OSError [WinError 1114] from torch or onnxruntime
almost always means the Microsoft Visual C++ Redistributable (x64) is
missing or outdated on this machine. Install it, then re-run this check:
  https://aka.ms/vs/17/release/vc_redist.x64.exe
"""


def main() -> int:
    failures: list[tuple[str, Exception]] = []
    for label, module_name in _CHECKS:
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 -- report every failure mode, not just ImportError
            print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
            failures.append((label, exc))
        else:
            print(f"[OK]   {label}")

    if failures:
        print(f"\n{len(failures)} PDF dependency import(s) failed.")
        if sys.platform == "win32":
            print(_WINDOWS_DLL_HINT)
        return 1

    print("\nAll PDF conversion dependencies imported cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
