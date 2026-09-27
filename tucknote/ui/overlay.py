"""Compact, draggable recording overlay widget for Thought Capture."""

from __future__ import annotations

import logging
from pathlib import Path
from PySide6.QtCore import Qt, QPoint, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget,
    QHBoxLayout,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QFrame,
    QApplication,
    QToolTip,
)
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QCursor, QMouseEvent

from tucknote.config import AppSettings
from tucknote.ui.icons import create_status_icon
from tucknote.ui.vector_icons import get_vector_icon
from tucknote.ui.screenshot import ScreenshotService

logger = logging.getLogger("tucknote")


class RecordingOverlay(QWidget):
    """Compact, frameless, always-on-top floating pill widget for recording and status."""

    # Signals
    toggle_recording_requested = Signal()
    cancel_recording_requested = Signal()
    open_library_requested = Signal()
    screenshot_attached = Signal(object)  # Path | None
    copy_text_requested = Signal(str)
    overlay_position_changed = Signal(int, int)
    hide_requested = Signal()

    def __init__(self, settings: AppSettings, parent=None):
        super().__init__(
            parent,
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool,
        )
        self.settings = settings
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self._drag_pos: QPoint | None = None
        self._current_state = "ready"
        self._attached_screenshot: Path | None = None
        self._last_saved_text: str | None = None
        self._elapsed_seconds = 0

        # Duration timer
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._on_timer_tick)

        # Reset timer after saved state
        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.setInterval(4000)
        self._reset_timer.timeout.connect(self._reset_to_ready)

        self._init_ui()
        self._restore_position()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)

        # Outer card frame
        self.card = QFrame(self)
        self.card.setObjectName("overlayCard")
        self.card.setStyleSheet(
            """
            #overlayCard {
                background-color: rgba(24, 24, 27, 0.92);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 20px;
            }
            """
        )

        card_layout = QHBoxLayout(self.card)
        card_layout.setContentsMargins(8, 4, 10, 4)
        card_layout.setSpacing(6)

        # 1. Main Mic / Record Button
        self.mic_btn = QPushButton()
        self.mic_btn.setFixedSize(32, 32)
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setIcon(create_status_icon("ready", 32))
        self.mic_btn.setIconSize(QSize(22, 22))
        self.mic_btn.setToolTip("Start Recording (Ctrl+Alt+Space)")
        self.mic_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2563eb;
                border: none;
                border-radius: 16px;
            }
            QPushButton:hover {
                background-color: #1d4ed8;
            }
            """
        )
        self.mic_btn.clicked.connect(self.toggle_recording_requested.emit)
        card_layout.addWidget(self.mic_btn)

        # 2. Status Label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 500;")
        card_layout.addWidget(self.status_label)

        # 3. Screenshot Button (visible during recording / ready)
        self.screenshot_btn = QPushButton()
        self.screenshot_btn.setIcon(get_vector_icon("camera", color="#e2e8f0", size=14))
        self.screenshot_btn.setFixedSize(26, 26)
        self.screenshot_btn.setCursor(Qt.PointingHandCursor)
        self.screenshot_btn.setToolTip("Add Screenshot")
        self.screenshot_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                border: none;
                border-radius: 13px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.2);
            }
            """
        )
        self.screenshot_btn.clicked.connect(self._on_capture_screenshot)
        card_layout.addWidget(self.screenshot_btn)

        # 4. Screenshot Thumbnail Preview (hidden by default)
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(36, 22)
        self.thumb_label.setStyleSheet("border: 1px solid #38bdf8; border-radius: 3px;")
        self.thumb_label.setScaledContents(True)
        self.thumb_label.setVisible(False)
        card_layout.addWidget(self.thumb_label)

        self.remove_screenshot_btn = QPushButton()
        self.remove_screenshot_btn.setIcon(get_vector_icon("x", color="#ffffff", size=10))
        self.remove_screenshot_btn.setFixedSize(16, 16)
        self.remove_screenshot_btn.setCursor(Qt.PointingHandCursor)
        self.remove_screenshot_btn.setToolTip("Remove Screenshot")
        self.remove_screenshot_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(239, 68, 68, 0.7);
                border: none;
                border-radius: 8px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 1.0);
            }
            """
        )
        self.remove_screenshot_btn.clicked.connect(self._on_remove_screenshot)
        self.remove_screenshot_btn.setVisible(False)
        card_layout.addWidget(self.remove_screenshot_btn)

        # 5. Cancel Button (visible only while recording)
        self.cancel_btn = QPushButton()
        self.cancel_btn.setIcon(get_vector_icon("x", color="#fca5a5", size=12))
        self.cancel_btn.setFixedSize(22, 22)
        self.cancel_btn.setCursor(Qt.PointingHandCursor)
        self.cancel_btn.setToolTip("Cancel recording")
        self.cancel_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(239, 68, 68, 0.25);
                border: 1px solid rgba(239, 68, 68, 0.4);
                border-radius: 11px;
            }
            QPushButton:hover {
                background-color: rgba(239, 68, 68, 0.8);
            }
            """
        )
        self.cancel_btn.clicked.connect(self.cancel_recording_requested.emit)
        self.cancel_btn.setVisible(False)
        card_layout.addWidget(self.cancel_btn)

        # 6. Copy text button (visible after saved)
        self.copy_btn = QPushButton()
        self.copy_btn.setIcon(get_vector_icon("copy", color="#38bdf8", size=13))
        self.copy_btn.setFixedSize(24, 24)
        self.copy_btn.setCursor(Qt.PointingHandCursor)
        self.copy_btn.setToolTip("Copy transcript to clipboard")
        self.copy_btn.setStyleSheet(
            """
            QPushButton {
                background-color: rgba(255, 255, 255, 0.12);
                border: none;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: #3b82f6;
            }
            """
        )
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        self.copy_btn.setVisible(False)
        card_layout.addWidget(self.copy_btn)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: rgba(255, 255, 255, 0.2);")
        card_layout.addWidget(sep)

        # 7. Library Button
        self.lib_btn = QPushButton()
        self.lib_btn.setIcon(get_vector_icon("layers", color="#94a3b8", size=14))
        self.lib_btn.setFixedSize(24, 24)
        self.lib_btn.setCursor(Qt.PointingHandCursor)
        self.lib_btn.setToolTip("Open Library")
        self.lib_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                border: none;
                border-radius: 12px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 0.15);
            }
            """
        )
        self.lib_btn.clicked.connect(self.open_library_requested.emit)
        card_layout.addWidget(self.lib_btn)

        # 8. Hide Overlay Button
        self.hide_btn = QPushButton("–")
        self.hide_btn.setFixedSize(20, 20)
        self.hide_btn.setCursor(Qt.PointingHandCursor)
        self.hide_btn.setToolTip("Hide Overlay to Tray")
        self.hide_btn.setStyleSheet(
            """
            QPushButton {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: #f8fafc;
            }
            """
        )
        self.hide_btn.clicked.connect(self._on_hide_clicked)
        card_layout.addWidget(self.hide_btn)

        main_layout.addWidget(self.card)

    def _on_hide_clicked(self) -> None:
        self.hide()
        self.hide_requested.emit()

    def _restore_position(self) -> None:
        """Restore position from settings, default to top-right screen margin."""
        screen = QApplication.primaryScreen()
        if not screen:
            self.move(100, 100)
            return

        geom = screen.availableGeometry()
        default_x = geom.right() - 340
        default_y = geom.top() + 40

        x = self.settings.overlay_x if self.settings.overlay_x is not None else default_x
        y = self.settings.overlay_y if self.settings.overlay_y is not None else default_y

        # Keep on screen
        x = max(geom.left(), min(x, geom.right() - 250))
        y = max(geom.top(), min(y, geom.bottom() - 80))

        self.move(x, y)

    def update_state(self, state: str, detail_message: str | None = None, result_text: str | None = None) -> None:
        """Update visual state and toggle buttons accordingly."""
        self._current_state = state

        if state == "recording":
            self._reset_timer.stop()
            self._elapsed_seconds = 0
            self._duration_timer.start()
            self.mic_btn.setIcon(create_status_icon("recording", 32))
            self.mic_btn.setStyleSheet(
                "QPushButton { background-color: #ef4444; border: none; border-radius: 16px; }"
                "QPushButton:hover { background-color: #dc2626; }"
            )
            self.status_label.setText("Recording (0:00)")
            self.status_label.setStyleSheet("color: #fca5a5; font-size: 12px; font-weight: bold;")
            self.cancel_btn.setVisible(True)
            self.screenshot_btn.setVisible(True)
            self.copy_btn.setVisible(False)

        elif state == "processing":
            self._duration_timer.stop()
            self.mic_btn.setIcon(create_status_icon("processing", 32))
            self.mic_btn.setStyleSheet(
                "QPushButton { background-color: #f59e0b; border: none; border-radius: 16px; }"
            )
            self.status_label.setText("Processing...")
            self.status_label.setStyleSheet("color: #fde68a; font-size: 12px; font-weight: 500;")
            self.cancel_btn.setVisible(False)
            self.copy_btn.setVisible(False)

        elif state == "saved":
            self._duration_timer.stop()
            self._last_saved_text = result_text
            self.mic_btn.setIcon(create_status_icon("ready", 32))
            self.mic_btn.setStyleSheet(
                "QPushButton { background-color: #10b981; border: none; border-radius: 16px; }"
            )
            self.status_label.setText("Saved!")
            self.status_label.setStyleSheet("color: #6ee7b7; font-size: 12px; font-weight: bold;")
            self.cancel_btn.setVisible(False)
            self.copy_btn.setVisible(bool(result_text))
            self._clear_screenshot_attachment()
            self._reset_timer.start()

        elif state == "error":
            self._duration_timer.stop()
            self.mic_btn.setIcon(create_status_icon("error", 32))
            self.mic_btn.setStyleSheet(
                "QPushButton { background-color: #ef4444; border: none; border-radius: 16px; }"
            )
            err_msg = detail_message or "Error"
            if len(err_msg) > 18:
                err_msg = err_msg[:15] + "..."
            self.status_label.setText(err_msg)
            self.status_label.setStyleSheet("color: #fca5a5; font-size: 12px; font-weight: 500;")
            self.cancel_btn.setVisible(False)
            self.copy_btn.setVisible(False)
            self._reset_timer.start()

        else:  # ready
            self._duration_timer.stop()
            self.mic_btn.setIcon(create_status_icon("ready", 32))
            self.mic_btn.setStyleSheet(
                "QPushButton { background-color: #2563eb; border: none; border-radius: 16px; }"
                "QPushButton:hover { background-color: #1d4ed8; }"
            )
            self.status_label.setText("Ready")
            self.status_label.setStyleSheet("color: #f8fafc; font-size: 12px; font-weight: 500;")
            self.cancel_btn.setVisible(False)
            self.screenshot_btn.setVisible(True)
            self.copy_btn.setVisible(False)

        self.adjustSize()

    def _on_timer_tick(self) -> None:
        self._elapsed_seconds += 1
        mins = self._elapsed_seconds // 60
        secs = self._elapsed_seconds % 60
        self.status_label.setText(f"Recording ({mins}:{secs:02d})")

    def _reset_to_ready(self) -> None:
        if self._current_state in ("saved", "error"):
            self.update_state("ready")

    def _on_capture_screenshot(self) -> None:
        """Capture screen without overlay, attach to current capture."""
        path = ScreenshotService.capture_screen(self)
        if path and path.exists():
            self._attached_screenshot = path
            pix = QPixmap(str(path))
            if not pix.isNull():
                thumb = pix.scaled(36, 22, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self.thumb_label.setPixmap(thumb)
                self.thumb_label.setVisible(True)
                self.remove_screenshot_btn.setVisible(True)
            self.screenshot_attached.emit(path)
            self.adjustSize()

    def _on_remove_screenshot(self) -> None:
        """User clicked remove screenshot."""
        self._clear_screenshot_attachment()
        self.screenshot_attached.emit(None)

    def _clear_screenshot_attachment(self) -> None:
        if self._attached_screenshot and self._attached_screenshot.exists():
            # If removed before saving, delete temp screenshot
            if self._current_state != "saved":
                try:
                    self._attached_screenshot.unlink()
                except Exception:
                    pass
        self._attached_screenshot = None
        self.thumb_label.clear()
        self.thumb_label.setVisible(False)
        self.remove_screenshot_btn.setVisible(False)
        self.adjustSize()

    def _on_copy_clicked(self) -> None:
        if self._last_saved_text:
            clipboard = QApplication.clipboard()
            clipboard.setText(self._last_saved_text)
            self.copy_text_requested.emit(self._last_saved_text)
            self.status_label.setText("Copied!")
            self.status_label.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold;")

    # Drag-and-drop window repositioning
    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            new_pos = event.globalPosition().toPoint() - self._drag_pos
            self.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None:
            self._drag_pos = None
            pos = self.pos()
            self.settings.overlay_x = pos.x()
            self.settings.overlay_y = pos.y()
            self.settings.save()
            self.overlay_position_changed.emit(pos.x(), pos.y())
            event.accept()
