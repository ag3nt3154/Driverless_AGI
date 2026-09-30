from __future__ import annotations

import json

import pytest

from pyside_gui.theme import TOKENS, css_variables, qcolor, qss, solid, with_theme
from pyside_gui.tool_labels import tool_kind, tool_label


def test_qss_replaces_tokens():
    assert qss("QWidget { background: @app_bg; color: @fg; }") == (
        f"QWidget {{ background: {TOKENS['app_bg']}; color: {TOKENS['fg']}; }}"
    )


def test_qss_unknown_token_fails_loudly():
    with pytest.raises(KeyError):
        qss("color: @no_such_token;")


def test_css_variables_and_template_slot():
    css = css_variables()
    assert f"--chat-bg: {TOKENS['chat_bg']};" in css
    assert f"--fg-secondary: {TOKENS['fg_secondary']};" in css
    assert with_theme("<style>/*@THEME@*/</style>") == f"<style>{css}</style>"


def test_qcolor_keeps_alpha_and_solid_flattens():
    colour = qcolor("fg_secondary")
    assert (colour.red(), colour.green(), colour.blue(), colour.alpha()) == (238, 237, 250, 140)
    assert solid("app_bg") == TOKENS["app_bg"]
    # 55% of rgb(238, 237, 250) over app_bg #101019
    assert solid("fg_secondary") == "#8a8a95"


def test_no_catppuccin_hex_left_in_qt_sources():
    from pathlib import Path
    import re

    root = Path(__file__).parents[1]
    catppuccin = re.compile(r"#(1e1e2e|181825|11111b|282839|313244|313147|45475a|cdd6f4|6c7086|89b4fa|1a3a5c)\b", re.I)
    offenders = [
        str(p.relative_to(root))
        for p in list(root.glob("*.py")) + list(root.glob("sidebars/*.py"))
        + list(root.glob("resources/*.css")) + list(root.glob("resources/notepad/*.css"))
        if catppuccin.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.parametrize("name, args, label", [
    ("read", {"path": "agent/loop.py"}, "Read agent/loop.py"),
    ("write", {"path": "a.txt", "content": "x"}, "Wrote a.txt"),
    ("bash", {"command": "pytest  -q\n tests"}, "Ran pytest -q tests"),
    ("grep", {"pattern": "foo", "path": "tools/"}, 'Searched "foo" in tools/'),
    ("grep", {"pattern": "foo"}, 'Searched "foo"'),
    ("copy", {"src": "a", "dst": "b"}, "Copied a → b"),
    ("web_search", {"query": "vditor"}, "Searched the web for vditor"),
    ("read_notepad", {}, "Read the notepad"),
    ("mystery_tool", {"task": "do it"}, "Mystery tool: do it"),
    ("mystery_tool", {}, "Mystery tool"),
    ("[explore] read", {"path": "x.py"}, "[explore] Read x.py"),
])
def test_tool_label(name, args, label):
    assert tool_label(name, json.dumps(args)) == label


def test_tool_label_survives_bad_json_and_truncates():
    assert tool_label("read", "{not json") == "Read"
    long = tool_label("bash", json.dumps({"command": "x" * 500}))
    assert len(long) == 90 and long.endswith("…")


def test_tool_kind():
    assert [tool_kind(n) for n in ("read", "edit", "bash", "grep", "web_fetch", "skill", "[sub] bash")] == [
        "file", "edit", "terminal", "search", "globe", "tool", "terminal",
    ]
