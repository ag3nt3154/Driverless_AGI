"""Single source of colour and type tokens for the whole PySide GUI.

Qt stylesheets and the web views (conversation pane, notepad) read the same
values: Qt through :func:`qss`, which swaps ``@token`` placeholders, and the web
pages through :func:`css_variables`, which is spliced into their HTML as
``--token`` custom properties.

Two palettes share one set of token names, :data:`DARK` (the default) and
:data:`LIGHT`. :func:`use` loads one into :data:`TOKENS`. It must run before
any widget module is imported, because those build their stylesheets at import
time. This module calls it on import with ``$DAGI_THEME`` or the saved
preference (:func:`save_preference`), so a switch applies on the next launch.

Dark: the structure (surface ladder, one foreground at four opacities) is
adapted from OpenGhost (https://github.com/ANDRETRIPOL/OpenGhost, (c) 2026
Andrew). OpenGhost's visual design is licensed for non-commercial use only:
keep this notice and do not ship this palette in a commercial product.
One hue (240°, ~20% saturation) for every surface, told apart by lightness
only — sidebars darkest, chat pane lighter, composer lifted — a cool off-white
foreground at four opacities, an indigo-blue accent, and colour reserved for
meaning: tool titles (sky), thinking (lavender), right-sidebar values (sand
tokens, mint context) and status (danger / success / warn / link).

Light: Material 3 as Google ships it in its own web apps
(https://m3.material.io): a tinted surface-container sidebar around a white
chat surface, on-surface #1f1f1f text at four opacities, a #0b57d0 primary,
secondary-container #d3e3fd for selection, tone-40 status colours, and Google
Sans / Roboto type where installed (Segoe UI otherwise).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path

from agent import DAGI_ROOT

log = logging.getLogger(__name__)

_FG = "238, 237, 250"

DARK: dict[str, str] = {
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
    "scrim": "rgba(0, 0, 0, 0.50)",  # behind modal overlays
    # Type.
    "font_ui": "'Segoe UI', system-ui, -apple-system, sans-serif",
    "font_mono": "'Cascadia Code', 'Consolas', ui-monospace, monospace",
    # Web views: CSS color-scheme (also Vditor's theme) and highlight.js style.
    "color_scheme": "dark",
    "hljs_style": "tokyo-night-dark",
}

_ON_SURFACE = "31, 31, 31"  # M3 on-surface #1f1f1f

LIGHT: dict[str, str] = {
    # Surfaces: M3 surface-container ladder from Google's neutral-blue palette.
    "contour": "#c4c7c5",           # outline-variant
    "app_bg": "#f0f4f9",            # surface-container-low: sidebars, menu bar
    "chat_bg": "#ffffff",           # surface: the conversation
    "contour_inner": "#e1e3e1",
    "popover_bg": "#ffffff",
    "menu_bg": "#ffffff",
    "border": "#dde3ea",            # divider
    "composer_bg": "#f0f4f9",       # filled input on the white surface
    "hover_bg": "#e1e5ea",          # on-surface 8% state layer, flattened
    "active_bg": "#d3e3fd",         # secondary-container: selected item
    "composer_border": "#c4c7c5",   # outline-variant
    "well_bg": f"rgba({_ON_SURFACE}, 0.04)",
    # Foreground: on-surface at four strengths (M3 disabled is 38%).
    "fg": f"rgba({_ON_SURFACE}, 0.92)",
    "fg_secondary": f"rgba({_ON_SURFACE}, 0.70)",   # ~ on-surface-variant #444746
    "fg_tertiary": f"rgba({_ON_SURFACE}, 0.42)",
    "fg_quaternary": f"rgba({_ON_SURFACE}, 0.12)",
    "fg_faint": f"rgba({_ON_SURFACE}, 0.05)",
    # Meaning only: tone-40 colours so text clears 4.5:1 on white.
    "danger": "rgb(179, 38, 30)",       # error #b3261e
    "success": "rgb(20, 108, 46)",
    "warn": "rgb(176, 96, 0)",
    "link": "rgb(11, 87, 208)",         # primary
    "selection": "rgba(11, 87, 208, 0.20)",
    "diff_removed": "rgb(179, 38, 30)",
    "diff_added": "rgb(20, 108, 46)",
    # Accent: primary #0b57d0, on-primary white.
    "accent": "#0b57d0",
    "on_accent": "#ffffff",
    "user_bubble_bg": "#e9eef6",        # surface-container-high
    "tool_fg": "#00639b",               # tertiary blue
    "thinking_fg": "#6750a4",           # M3 baseline primary (purple)
    "tokens_fg": "#8a5300",             # sand, darkened for white
    "context_fg": "#006a60",            # teal
    "scrim": "rgba(0, 0, 0, 0.32)",     # M3 scrim opacity
    "font_ui": "'Google Sans Text', 'Google Sans', 'Roboto', 'Segoe UI', system-ui, sans-serif",
    "font_mono": "'Roboto Mono', 'Cascadia Code', 'Consolas', ui-monospace, monospace",
    "color_scheme": "light",
    "hljs_style": "github",
}

PALETTES = {"dark": DARK, "light": LIGHT}
MODES = ("dark", "light", "system")
_SETTINGS = DAGI_ROOT / ".dagi" / "gui_settings.json"

TOKENS: dict[str, str] = {}
mode = "dark"  # name of the palette currently in TOKENS

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


def tint(name: str, alpha: float) -> str:
    """Token's colour at ``alpha`` as ``rgba()`` (status pills, icon states)."""
    r, g, b, _ = _rgba(TOKENS[name])
    return f"rgba({r}, {g}, {b}, {alpha:g})"


_SCROLLBAR_TEMPLATE = """
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 8px; margin: 2px; }
QScrollBar::handle { background: @fg_quaternary; border-radius: 3px; min-height: 24px; min-width: 24px; }
QScrollBar::handle:hover { background: @fg_tertiary; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""
SCROLLBAR_QSS = ""  # filled by use()


def css_variables() -> str:
    """Tokens as a ``:root`` block of CSS custom properties (``--app-bg`` …)."""
    body = "".join(
        f"--{name.replace('_', '-')}: {value};" for name, value in TOKENS.items()
    )
    return f":root{{{body}}}"


def with_theme(html: str) -> str:
    """Splice :func:`css_variables` into an HTML template's theme slot."""
    return html.replace("/*@THEME@*/", css_variables())


# ---- mode selection ------------------------------------------------------


def system_mode() -> str:
    """``"light"`` or ``"dark"`` from the OS app theme (dark if unknown)."""
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                return "light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "dark"
        except OSError:
            return "dark"
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return "dark"
    app = QGuiApplication.instance()
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Light:
        return "light"
    return "dark"


def load_preference(store: Path | None = None) -> str:
    """Saved choice (``dark`` / ``light`` / ``system``); ``$DAGI_THEME`` wins."""
    env = os.environ.get("DAGI_THEME", "").strip().lower()
    if env in MODES:
        return env
    store = store or _SETTINGS
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "dark"
    except (OSError, ValueError) as exc:
        log.warning("Ignoring unreadable GUI settings %s: %s", store, exc)
        return "dark"
    value = data.get("theme") if isinstance(data, dict) else None
    return value if value in MODES else "dark"


def save_preference(choice: str, store: Path | None = None) -> None:
    """Persist ``choice`` for the next launch, keeping other settings."""
    if choice not in MODES:
        raise ValueError(f"unknown theme {choice!r}; expected one of {MODES}")
    store = store or _SETTINGS
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data["theme"] = choice
    # A failed write must not break the GUI; the switch just won't persist.
    try:
        store.parent.mkdir(parents=True, exist_ok=True)
        store.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as exc:
        log.warning("Could not save GUI theme to %s: %s", store, exc)


def use(choice: str) -> str:
    """Load the palette for ``choice`` into :data:`TOKENS`; return its name.

    Widget modules read tokens at import, so call this before importing them.
    """
    global mode, SCROLLBAR_QSS
    if choice not in MODES:
        raise ValueError(f"unknown theme {choice!r}; expected one of {MODES}")
    mode = system_mode() if choice == "system" else choice
    TOKENS.clear()
    TOKENS.update(PALETTES[mode])
    SCROLLBAR_QSS = qss(_SCROLLBAR_TEMPLATE)
    return mode


def apply_to_app(app) -> None:
    """Match native Qt chrome (dialogs, tooltips, title bar) to the palette."""
    from PySide6.QtCore import Qt

    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):  # Qt 6.8+
        hints.setColorScheme(Qt.ColorScheme.Light if mode == "light" else Qt.ColorScheme.Dark)


use(load_preference())
