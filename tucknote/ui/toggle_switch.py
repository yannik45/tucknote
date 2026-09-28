"""Modern iOS / macOS / ChatGPT style pill toggle switch."""

from __future__ import annotations

from PySide6.QtCore import Qt, QSize, QPropertyAnimation, Property, QEasingCurve, Signal
from PySide6.QtGui import QPainter, QColor, QBrush, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget


class ToggleSwitch(QAbstractButton):
    """Minimalist, ultra-clean pill toggle switch with smooth animated thumb."""

    def __init__(
        self,
        parent: QWidget | None = None,
        active_color: str = "#18181b",
        inactive_color: str = "#e4e4e7",
        thumb_color: str = "#ffffff",
    ):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(False)
        self.setCursor(Qt.PointingHandCursor)

        self._active_color = QColor(active_color)
        self._inactive_color = QColor(inactive_color)
        self._thumb_color = QColor(thumb_color)

        self._thumb_pos: float = 0.0
        self._anim = QPropertyAnimation(self, b"thumb_pos", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)

        self.toggled.connect(self._on_toggled)

    def sizeHint(self) -> QSize:
        return QSize(42, 22)

    def minimumSizeHint(self) -> QSize:
        return QSize(42, 22)

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, pos: float) -> None:
        self._thumb_pos = pos
        self.update()

    thumb_pos = Property(float, _get_thumb_pos, _set_thumb_pos)

    def _on_toggled(self, checked: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        self._thumb_pos = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = h / 2.0

        # Background pill track
        track_color = self._active_color if self.isChecked() else self._inactive_color
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(track_color))
        painter.drawRoundedRect(0, 0, w, h, radius, radius)

        # Thumb circle dimensions
        thumb_diameter = h - 6  # 3px margin
        x_min = 3.0
        x_max = w - thumb_diameter - 3.0
        thumb_x = x_min + (x_max - x_min) * self._thumb_pos
        thumb_y = 3.0

        # Subtle shadow
        painter.setBrush(QBrush(QColor(0, 0, 0, 25)))
        painter.drawEllipse(thumb_x, thumb_y + 1, thumb_diameter, thumb_diameter)

        # White thumb circle
        painter.setBrush(QBrush(self._thumb_color))
        painter.drawEllipse(thumb_x, thumb_y, thumb_diameter, thumb_diameter)
        painter.end()
