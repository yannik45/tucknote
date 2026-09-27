"""Dynamic icon generator for Thought Capture tray and UI."""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen, QBrush


def create_status_icon(state: str = "ready", size: int = 64) -> QIcon:
    """Generate a crisp vector-like QIcon for tray status.
    
    States:
      - 'ready': Teal/Green circle with clean mic contour
      - 'recording': Vibrant Red recording dot with outer pulsing ring
      - 'processing': Amber/Orange indicator
      - 'error': Red warning badge
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    margin = 4.0
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    if state == "recording":
        # Red pulsing recording circle
        # Outer soft ring
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(239, 68, 68, 70)))
        painter.drawEllipse(rect)

        # Inner solid red circle
        inner_margin = size * 0.22
        inner_rect = QRectF(inner_margin, inner_margin, size - 2 * inner_margin, size - 2 * inner_margin)
        painter.setBrush(QBrush(QColor(239, 68, 68)))
        painter.drawEllipse(inner_rect)

    elif state == "processing":
        # Amber processing circle with dotted inner ring
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(245, 158, 11, 60)))
        painter.drawEllipse(rect)

        pen = QPen(QColor(245, 158, 11), size * 0.12, Qt.DashLine)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inner_margin = size * 0.22
        inner_rect = QRectF(inner_margin, inner_margin, size - 2 * inner_margin, size - 2 * inner_margin)
        painter.drawEllipse(inner_rect)

    elif state == "error":
        # Warning icon
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(239, 68, 68)))
        painter.drawEllipse(rect)

        # White exclamation mark
        painter.setPen(QPen(QColor(255, 255, 255), size * 0.14, Qt.SolidLine, Qt.RoundCap))
        cx = size / 2.0
        painter.drawLine(cx, size * 0.28, cx, size * 0.58)
        painter.drawPoint(cx, size * 0.74)

    else:
        # Ready: Elegant calm teal / blue badge with microphone dot
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(37, 99, 235)))  # Blue
        painter.drawEllipse(rect)

        # White dot / sound wave in center
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        inner_size = size * 0.32
        inner_rect = QRectF((size - inner_size) / 2, (size - inner_size) / 2, inner_size, inner_size)
        painter.drawEllipse(inner_rect)

    painter.end()
    return QIcon(pixmap)
