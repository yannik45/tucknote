"""System Tray Icon integration for Thought Capture (tucknote)."""

from __future__ import annotations

import logging
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QAction

from tucknote.ui.icons import create_status_icon

logger = logging.getLogger("tucknote")


class TraySignals(QObject):
    open_library_requested = Signal()
    open_settings_requested = Signal()
    toggle_overlay_requested = Signal()
    toggle_recording_requested = Signal()
    cancel_recording_requested = Signal()
    retry_last_requested = Signal()
    discard_last_requested = Signal()
    quit_requested = Signal()


class ThoughtCaptureTray(QSystemTrayIcon):
    """System Tray Icon displaying app status and providing quick actions."""

    def __init__(self, hotkey_str: str = "Ctrl+Alt+Space", parent=None):
        super().__init__(create_status_icon("ready"), parent)
        self.hotkey_str = hotkey_str
        self.signals = TraySignals()
        self.current_state = "ready"
        self._overlay_visible = True

        self._build_menu()
        self.setToolTip(f"Thought Capture — Ready ({self.hotkey_str})")
        self.activated.connect(self._on_activated)

    def _build_menu(self) -> None:
        self.menu = QMenu()

        # Header status label
        self.status_action = QAction(f"Status: Ready ({self.hotkey_str})", self.menu)
        self.status_action.setEnabled(False)
        self.menu.addAction(self.status_action)

        self.menu.addSeparator()

        # Overlay Toggle
        self.overlay_action = QAction("Hide Overlay", self.menu)
        self.overlay_action.triggered.connect(self.signals.toggle_overlay_requested.emit)
        self.menu.addAction(self.overlay_action)

        # Library
        self.open_lib_action = QAction("Open Library...", self.menu)
        self.open_lib_action.triggered.connect(self.signals.open_library_requested.emit)
        self.menu.addAction(self.open_lib_action)

        # Settings
        self.open_settings_action = QAction("Settings...", self.menu)
        self.open_settings_action.triggered.connect(self.signals.open_settings_requested.emit)
        self.menu.addAction(self.open_settings_action)

        self.menu.addSeparator()

        # Manual recording toggle (useful if hotkey conflicted)
        self.toggle_rec_action = QAction(f"Start Recording ({self.hotkey_str})", self.menu)
        self.toggle_rec_action.triggered.connect(self.signals.toggle_recording_requested.emit)
        self.menu.addAction(self.toggle_rec_action)

        # Cancel recording
        self.cancel_rec_action = QAction("Cancel Recording", self.menu)
        self.cancel_rec_action.setEnabled(False)
        self.cancel_rec_action.triggered.connect(self.signals.cancel_recording_requested.emit)
        self.menu.addAction(self.cancel_rec_action)

        # Retry / Discard on error
        self.retry_action = QAction("Retry Last Recording", self.menu)
        self.retry_action.setVisible(False)
        self.retry_action.triggered.connect(self.signals.retry_last_requested.emit)
        self.menu.addAction(self.retry_action)

        self.discard_action = QAction("Discard Failed Recording", self.menu)
        self.discard_action.setVisible(False)
        self.discard_action.triggered.connect(self.signals.discard_last_requested.emit)
        self.menu.addAction(self.discard_action)

        self.menu.addSeparator()

        # Quit
        self.quit_action = QAction("Quit", self.menu)
        self.quit_action.triggered.connect(self.signals.quit_requested.emit)
        self.menu.addAction(self.quit_action)

        self.setContextMenu(self.menu)

    def set_overlay_visible(self, visible: bool) -> None:
        self._overlay_visible = visible
        self.overlay_action.setText("Hide Overlay" if visible else "Show Overlay")

    def update_state(self, state: str, detail_message: str | None = None) -> None:
        """Update the visual state of the tray icon and context menu."""
        self.current_state = state
        self.setIcon(create_status_icon(state))

        if state == "recording":
            self.setToolTip(f"Tucknote — Recording... ({self.hotkey_str} to finish)")
            self.status_action.setText("Status: Recording...")
            self.toggle_rec_action.setText(f"Finish Recording ({self.hotkey_str})")
            self.toggle_rec_action.setEnabled(True)
            self.cancel_rec_action.setEnabled(True)
            self.retry_action.setVisible(False)
            self.discard_action.setVisible(False)

        elif state == "processing":
            self.setToolTip("Tucknote — Processing recording...")
            self.status_action.setText("Status: Processing...")
            self.toggle_rec_action.setText("Processing...")
            self.toggle_rec_action.setEnabled(False)
            self.cancel_rec_action.setEnabled(False)
            self.retry_action.setVisible(False)
            self.discard_action.setVisible(False)

        elif state == "error":
            err_text = detail_message or "Error occurred"
            self.setToolTip(f"Tucknote — Error: {err_text}")
            self.status_action.setText(f"Status: Error ({err_text})")
            self.toggle_rec_action.setText(f"New Recording ({self.hotkey_str})")
            self.toggle_rec_action.setEnabled(True)
            self.cancel_rec_action.setEnabled(False)
            self.retry_action.setVisible(True)
            self.discard_action.setVisible(True)

        else:  # ready
            self.setToolTip(f"Tucknote — Ready ({self.hotkey_str})")
            self.status_action.setText(f"Status: Ready ({self.hotkey_str})")
            self.toggle_rec_action.setText(f"Start Recording ({self.hotkey_str})")
            self.toggle_rec_action.setEnabled(True)
            self.cancel_rec_action.setEnabled(False)
            self.retry_action.setVisible(False)
            self.discard_action.setVisible(False)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.signals.open_library_requested.emit()
