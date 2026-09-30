"""Single source of colour and type tokens for the whole PySide GUI.

Qt stylesheets and the web views (conversation pane, notepad) read the same
values: Qt through :func:`qss`, which swaps ``@token`` placeholders, and the web
pages through :func:`css_variables`, which is spliced into their HTML as
``--token`` custom properties.

The palette is a neutral dark theme adapted from OpenGhost
(https://github.com/ANDRETRIPOL/OpenGhost, (c) 2026 Andrew). OpenGhost's
visual design is licensed for non-commercial use only: keep this notice and do
not ship this palette in a commercial product.

Principles: grey surfaces, one foreground colour at four opacities, colour only
for meaning (danger / success / warn / link), a white accent.
"""
from __future__ import annotations

import re

_FG = "255, 255, 255"

TOKENS: dict[str, str] = {
    # Surfaces, darkest to lightest.
    "contour": "#111111",
    "app_bg": "#161616",
    "chat_bg": "#191919",
    "composer_bg": "#1e1e1e",
    "contour_inner": "#202020",
    "popover_bg": "#212121",
    "composer_border": "#262626",
    "hover_bg": "#242424",
    "menu_bg": "#242424",
    "active_bg": "#272727",
    "border": "#2c2c2c",
    "well_bg": "rgba(0, 0, 0, 0.28)",
    # Foreground: one colour, four strengths.
    "fg": f"rgba({_FG}, 0.85)",
    "fg_secondary": f"rgba({_FG}, 0.55)",
    "fg_tertiary": f"rgba({_FG}, 0.25)",
    "fg_quaternary": f"rgba({_FG}, 0.10)",
    "fg_faint": f"rgba({_FG}, 0.05)",
    # Meaning only.
    "danger": "rgb(255, 115, 105)",
    "success": "rgb(110, 205, 140)",
    "warn": "rgb(255, 180, 96)",
    "link": "rgb(140, 190, 255)",
    "selection": "rgba(130, 180, 245, 0.35)",
    "diff_removed": "rgb(255, 188, 181)",
    "diff_added": "rgb(192, 238, 206)",
    # Accent: white, with near-black on top of it.
    "accent": "#fafafa",
    "on_accent": "#0f0f0f",
    "user_bubble_bg": "#2a2a2a",
    # Type.
    "font_ui": "'Segoe UI', system-ui, -apple-system, sans-serif",
    "font_mono": "'Cascadia Code', 'Consolas', ui-monospace, monospace",
}

_PLACEHOLDER = re.compile(r"@([a-z_]+)")


def qss(template: str) -> str:
    """Return ``template`` with every ``@token`` replaced by its value.

    Unknown tokens raise ``KeyError`` so a typo fails loudly instead of
    silently producing an invalid stylesheet.
    """
    return _PLACEHOLDER.sub(lambda m: TOKENS[m.group(1)], template)


_RGBA = re.compile(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)")


def _rgba(value: str) -> tuple[int, int, int, float]:
    if value.startswith("#"):
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16), 1.0
    m = _RGBA.fullmatch(value.strip())
    if not m:
        raise ValueError(f"not a colour token: {value!r}")
    r, g, b, a = m.groups()
    return int(r), int(g), int(b), float(a) if a is not None else 1.0


def qcolor(name: str):
    """Token as a ``QColor`` (keeps alpha; QColor cannot parse ``rgba()``)."""
    from PySide6.QtGui import QColor

    r, g, b, a = _rgba(TOKENS[name])
    return QColor(r, g, b, round(a * 255))


def solid(name: str, over: str = "app_bg") -> str:
    """Token flattened onto a surface as ``#rrggbb``, for Qt rich text and
    other places that ignore alpha."""
    r, g, b, a = _rgba(TOKENS[name])
    br, bg, bb, _ = _rgba(TOKENS[over])
    mix = [round(c * a + base * (1 - a)) for c, base in ((r, br), (g, bg), (b, bb))]
    return "#" + "".join(f"{c:02x}" for c in mix)


def css_variables() -> str:
    """Tokens as a ``:root`` block of CSS custom properties (``--app-bg`` …)."""
    body = "".join(
        f"--{name.replace('_', '-')}: {value};" for name, value in TOKENS.items()
    )
    return f":root{{{body}}}"


def with_theme(html: str) -> str:
    """Splice :func:`css_variables` into an HTML template's theme slot."""
    return html.replace("/*@THEME@*/", css_variables())
