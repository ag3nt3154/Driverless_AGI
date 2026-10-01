"""Context meter: a small ring in the composer showing context-window use.

It mirrors the right sidebar's CONTEXT total (system prompt + history +
reserve), so 100% is exactly where the loop compacts. Neutral below 70%,
``warn`` from 70%, ``danger`` from 90%. Hidden until the first update and
whenever the model's context window is unknown. Display only: clicks do
nothing.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from pyside_gui.theme import qcolor

WARN_AT = 0.70
DANGER_AT = 0.90
_SIZE = 18
_STROKE = 2.5


def meter_role(usage: float) -> str:
    """Theme token for the filled arc at ``usage`` (0.0–1.0+)."""
    if usage >= DANGER_AT:
        return "danger"
    if usage >= WARN_AT:
        return "warn"
    return "fg_secondary"


class ContextMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("context-meter")
        self.setFixedSize(QSize(_SIZE + 10, 30))
        self._usage = 0.0
        self.hide()

    @property
    def usage(self) -> float:
        return self._usage

    def set_usage(self, used: int, window: int) -> None:
        if window <= 0:
            self.hide()
            return
        self._usage = used / window
        pct = round(self._usage * 100)
        self.setToolTip(
            f"Context {pct}% · {used:,} / {window:,} tokens\n"
            "Includes the reserve; compacts at 100%"
        )
        self.show()
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        inset = _STROKE / 2 + 0.5
        side = _SIZE - 2 * inset
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

        track = QPen(qcolor("fg_quaternary"), _STROKE)
        painter.setPen(track)
        painter.drawEllipse(rect)

        fill = min(self._usage, 1.0)
        if fill > 0:
            arc = QPen(qcolor(meter_role(self._usage)), _STROKE)
            arc.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(arc)
            # Qt angles are 1/16°, counter-clockwise from 3 o'clock; start at
            # 12 o'clock and sweep clockwise.
            painter.drawArc(rect, 90 * 16, -round(fill * 360 * 16))
        painter.end()
