"""Self-check for the conversation pane's markdown engine (vendored Vditor).

    python -m pyside_gui.check_render

Verifies the vendored files are present and unmodified against git, then
loads the real conversation page and renders a sample. Exit code 0 = OK.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pyside_gui  # noqa: F401 - register DLL paths before Qt imports
from PySide6.QtCore import QEventLoop, QTimer, qVersion
from PySide6.QtWidgets import QApplication

VDITOR = Path(__file__).parent / "resources" / "vditor"
REQUIRED = [
    "dist/index.min.js",
    "dist/index.css",
    "dist/js/lute/lute.min.js",
    "dist/js/i18n/en_US.js",
    "dist/js/highlight.js/highlight.min.js",
    "dist/js/katex/katex.min.js",
]
SAMPLE = "**bold** `code` $a^2$\n\n- item"
PROBE = """JSON.stringify((() => { try {
    const el = document.createElement('div');
    renderMarkdownInto(el, %s);
    return {lute: typeof Lute, vditor: typeof Vditor,
            fallback: el.classList.contains('md-fallback'),
            strong: !!el.querySelector('strong'), li: !!el.querySelector('li'),
            chromium: (navigator.userAgent.match(/Chrome\\/[\\d.]+/) || [''])[0]};
} catch (e) { return {error: String(e)}; } })())"""


def _check_files() -> list[str]:
    problems = [f"missing: {VDITOR / rel}" for rel in REQUIRED if not (VDITOR / rel).is_file()]
    try:
        changed = subprocess.run(
            ["git", "status", "--porcelain", "--", str(VDITOR)],
            capture_output=True, text=True, cwd=VDITOR, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"(git check skipped: {exc})")
    else:
        problems += [f"differs from git: {line}" for line in changed.splitlines()]
    return problems


def _check_page() -> dict:
    app = QApplication.instance() or QApplication(sys.argv)
    from pyside_gui.conversation import ConversationView

    view = ConversationView()
    loop = QEventLoop()
    view.loadFinished.connect(loop.quit)
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    if not view._ready:
        return {"error": "conversation page failed to load"}
    result: list = []
    view.page().runJavaScript(PROBE % json.dumps(SAMPLE), lambda r: (result.append(r), loop.quit()))
    QTimer.singleShot(15000, loop.quit)
    loop.exec()
    del app
    return json.loads(result[0]) if result else {"error": "page did not answer"}


def main() -> int:
    print(f"vditor dir: {VDITOR}")
    print(f"version:    {(VDITOR / 'VERSION').read_text(encoding='utf-8').strip() if (VDITOR / 'VERSION').is_file() else '?'}")
    print(f"Qt:         {qVersion()}")
    problems = _check_files()
    page = _check_page()
    print(f"page:       {json.dumps(page)}")
    if "error" in page:
        problems.append(f"render error: {page['error']}")
    elif page["fallback"] or not (page["strong"] and page["li"]):
        problems.append("markdown did not render (see pyside_worker.log for the page error)")
    for p in problems:
        print(f"FAIL  {p}")
    print("OK - markdown engine loads and renders" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
