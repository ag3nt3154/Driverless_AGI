"""Monochrome line icons for Qt widgets, drawn from inline SVG.

``icon("plus")`` returns a QIcon with normal / active / disabled states in the
theme's secondary, primary and tertiary foreground strengths. The same glyph
shapes are used by the conversation pane (resources/conversation.js).
"""
from __future__ import annotations

import re
from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from pyside_gui.theme import TOKENS, tint

_PATHS: dict[str, str] = {
    "history": '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "file": '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
    "plan": '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6l1 1 2-2M4 12l1 1 2-2"/><circle cx="5" cy="18" r="1"/>',
    "board": '<path d="M4 5h16v11H9l-5 4z"/>',
    "agents": '<circle cx="9" cy="8" r="3"/><path d="M3 19c0-3.3 2.7-5 6-5s6 1.7 6 5"/>'
              '<circle cx="17" cy="9" r="2.3"/><path d="M16.5 14c2.6.2 4.5 1.9 4.5 5"/>',
    "panel_left": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M9 4v16"/>',
    "panel_right": '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M15 4v16"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "arrow_up": '<path d="M12 19V5M6 11l6-6 6 6"/>',
    "arrow_down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
    "spark": '<path d="M12 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
}
_FILLED: dict[str, str] = {
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2.5"/>',
}

# Stroke/fill strengths for the three icon states (see theme fg opacities).
_STATES = {
    QIcon.Mode.Normal: TOKENS["fg_secondary"],
    QIcon.Mode.Active: TOKENS["fg"],
    QIcon.Mode.Selected: tint("fg", 0.95),
    QIcon.Mode.Disabled: TOKENS["fg_tertiary"],
}


def _paint(color: str) -> tuple[str, float]:
    """``rgba(r,g,b,a)`` -> (``#rrggbb``, a): QtSvg (SVG Tiny) has no rgba()."""
    m = re.fullmatch(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)", color.strip())
    if not m:
        return color, 1.0
    r, g, b, a = m.groups()
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}", float(a) if a is not None else 1.0


def _svg(name: str, color: str, stroke_width: float) -> bytes:
    paint, opacity = _paint(color)
    if name in _FILLED:
        body = f'<g fill="{paint}" fill-opacity="{opacity}" stroke="none">{_FILLED[name]}</g>'
    else:
        body = (
            f'<g fill="none" stroke="{paint}" stroke-opacity="{opacity}" stroke-width="{stroke_width}" '
            f'stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</g>'
        )
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{body}</svg>'.encode()


def pixmap(name: str, color: str, size: int = 18, stroke_width: float = 1.7) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(_svg(name, color, stroke_width)))
    ratio = 2
    pm = QPixmap(size * ratio, size * ratio)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter, QRectF(0, 0, size * ratio, size * ratio))
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


@lru_cache(maxsize=None)
def icon(name: str, size: int = 18, color: str | None = None, stroke_width: float = 1.7) -> QIcon:
    """Themed icon. With ``color`` every state uses that one colour."""
    result = QIcon()
    for mode, state_color in _STATES.items():
        result.addPixmap(pixmap(name, color or state_color, size, stroke_width), mode)
    # Checked buttons (sidebar rail) show the brightest strength.
    on = pixmap(name, color or _STATES[QIcon.Mode.Selected], size, stroke_width)
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected):
        result.addPixmap(on, mode, QIcon.State.On)
    return result
