from __future__ import annotations

import base64
import hashlib
import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "vendor_vditor", Path(__file__).resolve().parent.parent / "scripts" / "vendor_vditor.py"
)
vendor_vditor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vendor_vditor)


@pytest.mark.parametrize("name, expected", [
    ("package/dist/index.min.js", "dist/index.min.js"),
    ("package/dist/js/lute/lute.min.js", "dist/js/lute/lute.min.js"),
    ("package/dist/js/katex/fonts/KaTeX_Main-Regular.woff2", "dist/js/katex/fonts/KaTeX_Main-Regular.woff2"),
    ("package/LICENSE", "LICENSE"),
    ("package/dist/js/katex/fonts/KaTeX_Main-Regular.ttf", None),
    ("package/dist/js/mermaid/mermaid.min.js", "dist/js/mermaid/mermaid.min.js"),
    ("package/dist/js/echarts/echarts.min.js", None),
    ("package/dist/js/i18n/zh_CN.js", None),
    ("package/dist/js/highlight.js/styles/github.min.css", "dist/js/highlight.js/styles/github.min.css"),
    ("package/dist/js/highlight.js/styles/github-dark.min.css", None),
    ("package/dist/css/content-theme/light.css", "dist/css/content-theme/light.css"),
    ("package/src/index.ts", None),
    ("dist/index.min.js", None),
])
def test_select_member(name, expected):
    assert vendor_vditor.select_member(name) == expected


def test_verify_integrity_accepts_match_and_rejects_mismatch():
    data = b"vditor"
    good = "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode()
    vendor_vditor._verify_integrity(data, good)
    with pytest.raises(ValueError):
        vendor_vditor._verify_integrity(b"tampered", good)


def test_vendored_tree_is_complete():
    root = vendor_vditor._DEST
    for rel in vendor_vditor._KEEP_FILES:
        assert (root / rel).is_file(), rel
    assert (root / "VERSION").read_text(encoding="utf-8").startswith(f"vditor {vendor_vditor.VDITOR_VERSION}")
    assert list((root / "dist/js/katex/fonts").glob("*.woff2"))
