#!/usr/bin/env python3
"""
scripts/vendor_vditor.py — Vendor a trimmed Vditor build for the pet notepad.

Vditor's built bundle is published only to npm (the GitHub repo ships no
dist/ and no release assets), so this maintainer-only script downloads the
pinned npm tarball once, verifies its sha512 integrity, and extracts just the
files the notepad and conversation pane need into pyside_gui/resources/vditor/. The result
is committed, so a plain git clone of dagi works offline with no Node/npm.

The dist/ layout is preserved because Vditor resolves its lazy-loaded assets
as ``<cdn>/dist/js/...``; the notepad points ``cdn`` at the vendored folder.

Usage:
    conda run -n dagi python scripts/vendor_vditor.py [--version 3.11.3]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

VDITOR_VERSION = "3.11.3"
# highlight.js styles per GUI theme (dark, light); see pyside_gui/theme.py.
HLJS_STYLES = ("tokyo-night-dark", "github")
_REGISTRY = "https://registry.npmjs.org/vditor"
_DEST = Path(__file__).resolve().parent.parent / "pyside_gui" / "resources" / "vditor"

# Exact files kept from the tarball (paths relative to the package root).
_KEEP_FILES = frozenset({
    "LICENSE",
    "dist/index.min.js",
    "dist/index.css",
    "dist/css/content-theme/dark.css",
    "dist/css/content-theme/light.css",
    "dist/js/lute/lute.min.js",
    "dist/js/katex/katex.min.js",
    "dist/js/katex/katex.min.css",
    "dist/js/katex/mhchem.min.js",
    "dist/js/icons/ant.js",
    "dist/js/i18n/en_US.js",
    "dist/js/mermaid/mermaid.min.js",
    "dist/js/highlight.js/LICENSE",
    "dist/js/highlight.js/highlight.min.js",
    "dist/js/highlight.js/third-languages.js",
    *(f"dist/js/highlight.js/styles/{style}.min.css" for style in HLJS_STYLES),
})
# Directories whose files are kept when they match the suffix.
_KEEP_DIR_SUFFIX = (("dist/js/katex/fonts/", ".woff2"),)


def select_member(name: str) -> str | None:
    """Map a tarball member name to its vendored relative path, or None to skip."""
    prefix = "package/"
    if not name.startswith(prefix):
        return None
    rel = name[len(prefix):]
    if rel in _KEEP_FILES:
        return rel
    for directory, suffix in _KEEP_DIR_SUFFIX:
        if rel.startswith(directory) and rel.endswith(suffix) and "/" not in rel[len(directory):]:
            return rel
    return None


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resp:  # noqa: S310 - fixed https registry URL
        return resp.read()


def _verify_integrity(data: bytes, integrity: str) -> None:
    algo, _, expected = integrity.partition("-")
    if algo != "sha512":
        raise ValueError(f"Unsupported integrity algorithm: {algo}")
    actual = base64.b64encode(hashlib.sha512(data).digest()).decode()
    if actual != expected:
        raise ValueError("Tarball sha512 integrity mismatch")


def vendor(version: str, dest: Path = _DEST) -> list[str]:
    meta = json.loads(_fetch(f"{_REGISTRY}/{version}"))
    tarball = _fetch(meta["dist"]["tarball"])
    _verify_integrity(tarball, meta["dist"]["integrity"])

    if dest.exists():
        shutil.rmtree(dest)
    written: list[str] = []
    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as tar:
        for member in tar.getmembers():
            rel = select_member(member.name) if member.isfile() else None
            if rel is None:
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tar.extractfile(member)
            assert src is not None
            target.write_bytes(src.read())
            written.append(rel)
    (dest / "VERSION").write_text(f"vditor {version} (npm, sha512 verified)\n", encoding="utf-8")
    missing = sorted(_KEEP_FILES - set(written))
    if missing:
        raise RuntimeError(f"Expected files missing from tarball: {missing}")
    return sorted(written)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", default=VDITOR_VERSION)
    args = parser.parse_args()
    files = vendor(args.version)
    total = sum((_DEST / f).stat().st_size for f in files)
    print(f"Vendored vditor {args.version}: {len(files)} files, {total / 1e6:.1f} MB -> {_DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
