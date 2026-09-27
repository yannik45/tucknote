"""Screen capture helper for Thought Capture attachments."""

from __future__ import annotations

import time
import uuid
import logging
from pathlib import Path
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QWidget, QApplication

from tucknote.config import get_screenshots_dir

logger = logging.getLogger("tucknote")


class ScreenshotService:
    """Handles conscious screen capturing without overlay window obstruction."""

    @staticmethod
    def capture_screen(overlay_widget: QWidget | None = None) -> Path | None:
        """Capture the primary screen to a local PNG file while hiding the overlay.
        
        Returns the Path to the saved PNG image, or None if capture failed.
        """
        was_visible = False
        if overlay_widget and overlay_widget.isVisible():
            was_visible = True
            overlay_widget.hide()
            # Process events so the window disappears from screen before grab
            QApplication.processEvents()
            time.sleep(0.06)

        try:
            screen = QGuiApplication.primaryScreen()
            if not screen:
                logger.warning("No primary screen detected for screenshot capture.")
                return None

            pixmap = screen.grabWindow(0)
            if pixmap.isNull():
                logger.warning("Captured pixmap was null or empty.")
                return None

            out_dir = get_screenshots_dir()
            filename = f"screenshot_{uuid.uuid4().hex[:12]}.png"
            file_path = out_dir / filename

            ok = pixmap.save(str(file_path), "PNG")
            if not ok:
                logger.error("Failed saving screenshot to %s", file_path)
                return None

            logger.info("Screenshot successfully captured: %s (%dx%d)", filename, pixmap.width(), pixmap.height())
            return file_path

        except Exception as e:
            logger.error("Error capturing screen: %s", e)
            return None

        finally:
            if was_visible and overlay_widget:
                overlay_widget.show()
                QApplication.processEvents()
