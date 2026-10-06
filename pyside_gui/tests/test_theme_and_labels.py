from __future__ import annotations

import json

import pytest

from pyside_gui import theme
from pyside_gui.theme import TOKENS, css_variables, qcolor, qss, solid, tint, with_theme
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


def test_palettes_share_token_names():
    assert set(theme.LIGHT) == set(theme.DARK)
    assert theme.mode == "dark" and TOKENS == theme.DARK


def test_use_swaps_tokens_in_place_and_rebuilds_scrollbar():
    try:
        assert theme.use("light") == "light"
        assert TOKENS["chat_bg"] == "#ffffff"
        assert theme.LIGHT["fg_quaternary"] in theme.SCROLLBAR_QSS
        assert "--color-scheme: light;" in css_variables()
    finally:
        theme.use("dark")
    assert TOKENS["chat_bg"] == theme.DARK["chat_bg"]
    with pytest.raises(ValueError):
        theme.use("sepia")


def test_tint_sets_alpha():
    assert tint("success", 0.14) == "rgba(110, 205, 140, 0.14)"
    assert tint("accent", 1) == "rgba(86, 81, 184, 1)"


def test_light_text_contrast_on_white():
    def luminance(hex_colour):
        def channel(c):
            c /= 255
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    try:
        theme.use("light")
        for name in ("fg", "fg_secondary", "danger", "success", "warn", "link",
                     "tool_fg", "thinking_fg", "tokens_fg", "context_fg"):
            ratio = (1.05) / (luminance(solid(name, over="chat_bg")) + 0.05)
            assert ratio >= 4.5, (name, ratio)
    finally:
        theme.use("dark")


def test_preference_round_trip_and_env_override(tmp_path, monkeypatch):
    store = tmp_path / "gui_settings.json"
    store.write_text('{"other": 1}', encoding="utf-8")
    monkeypatch.delenv("DAGI_THEME", raising=False)
    theme.save_preference("light", store)
    assert theme.load_preference(store) == "light"
    assert json.loads(store.read_text(encoding="utf-8")) == {"other": 1, "theme": "light"}
    monkeypatch.setenv("DAGI_THEME", "system")
    assert theme.load_preference(store) == "system"
    monkeypatch.delenv("DAGI_THEME")
    store.write_text("not json", encoding="utf-8")
    assert theme.load_preference(store) == "dark"
    assert theme.load_preference(tmp_path / "missing.json") == "dark"
    with pytest.raises(ValueError):
        theme.save_preference("sepia", store)


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
