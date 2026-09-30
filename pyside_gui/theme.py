"""Single source of colour and type tokens for the whole PySide GUI.

Qt stylesheets and the web views (conversation pane, notepad) read the same
values: Qt through :func:`qss`, which swaps ``@token`` placeholders, and the web
pages through :func:`css_variables`, which is spliced into their HTML as
``--token`` custom properties.

The structure (surface ladder, one foreground at four opacities) is adapted
from OpenGhost (https://github.com/ANDRETRIPOL/OpenGhost, (c) 2026 Andrew).
OpenGhost's visual design is licensed for non-commercial use only: keep this
notice and do not ship this palette in a commercial product.

Palette: one hue (240°, ~20% saturation) for every surface, told apart by
lightness only — sidebars darkest, chat pane lighter, composer lifted — a cool
off-white foreground at four opacities, an indigo-blue accent, and colour
reserved for meaning: tool titles (sky), thinking (lavender), right-sidebar
values (sand tokens, mint context) and status (danger / success / warn / link).
"""
from __future__ import annotations

import re

_FG = "238, 237, 250"

TOKENS: dict[str, str] = {
    # Surfaces, all hsl(240°, ~20%): sidebars 8%, chat 12%, composer 17%.
    "contour": "#0a0a10",
    "app_bg": "#101019",
    "chat_bg": "#191924",
    "contour_inner": "#1d1d2a",
    "popover_bg": "#20202f",
    "menu_bg": "#232332",
    "border": "#242432",
    "composer_bg": "#232334",
    "hover_bg": "#252535",
    "active_bg": "#2a2a3f",
    "composer_border": "#323248",
    "well_bg": "rgba(6, 6, 16, 0.35)",
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
    "link": "rgb(150, 170, 255)",
    "selection": "rgba(110, 104, 225, 0.40)",
    "diff_removed": "rgb(255, 188, 181)",
    "diff_added": "rgb(192, 238, 206)",
    # Accent: indigo blue (Coronation Blue nudged bluer), white on top.
    "accent": "#5651b8",
    "on_accent": "#ffffff",
    "user_bubble_bg": "#2c2c44",
    # Text roles in the chat pane (user text stays plain fg: the bubble marks it).
    "tool_fg": "#8db8e2",        # tool call title: sky blue
    "thinking_fg": "#b09bd4",    # thinking block: soft lavender
    # Right sidebar values (labels stay dim).
    "tokens_fg": "#e4c081",      # token counts: sand
    "context_fg": "#81cfb3",     # context breakdown: mint
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


SCROLLBAR_QSS = qss("""
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle { background: @fg_quaternary; border-radius: 3px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: @fg_tertiary; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
""")


def css_variables() -> str:
    """Tokens as a ``:root`` block of CSS custom properties (``--app-bg`` …)."""
    body = "".join(
        f"--{name.replace('_', '-')}: {value};" for name, value in TOKENS.items()
    )
    return f":root{{{body}}}"


def with_theme(html: str) -> str:
    """Splice :func:`css_variables` into an HTML template's theme slot."""
    return html.replace("/*@THEME@*/", css_variables())
