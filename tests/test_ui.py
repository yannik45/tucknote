"""Tests for UI components (Tray and Library Window) with PySide6."""

import sys
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
import pytest

from tucknote.storage.models import Note
from tucknote.storage.repository import NoteRepository
from tucknote.ui.icons import create_status_icon
from tucknote.ui.tray import ThoughtCaptureTray
from tucknote.ui.library_window import LibraryWindow


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if not app:
        app = QApplication([])
    return app


def test_icons_generation(qapp):
    for state in ["ready", "recording", "processing", "error"]:
        icon = create_status_icon(state)
        assert not icon.isNull()


def test_tray_state_updates(qapp):
    tray = ThoughtCaptureTray("Ctrl+Alt+Space")
    assert tray.current_state == "ready"

    tray.update_state("recording")
    assert tray.current_state == "recording"
    assert "Recording" in tray.status_action.text()
    assert tray.cancel_rec_action.isEnabled() is True

    tray.update_state("processing")
    assert tray.current_state == "processing"
    assert tray.toggle_rec_action.isEnabled() is False

    tray.update_state("error", "Transcription error")
    assert tray.current_state == "error"
    assert tray.retry_action.isVisible() is True
    assert tray.discard_action.isVisible() is True

    tray.update_state("ready")
    assert tray.current_state == "ready"


def test_library_window_interaction(qapp, tmp_path: Path):
    db_file = tmp_path / "ui_test.db"
    repo = NoteRepository(db_file)

    # Seed 2 notes
    note1 = Note(
        id="n1",
        captured_at_utc="2026-09-27T14:00:00+00:00",
        transcript="Fix the connection retry loop",
        application="Code.exe",
        window_title="client.py - Visual Studio Code",
    )
    note2 = Note(
        id="n2",
        captured_at_utc="2026-09-27T15:00:00+00:00",
        transcript="Check documentation on GitHub",
        application="msedge.exe",
        window_title="GitHub - Issue #12",
    )
    repo.save(note1)
    repo.save(note2)

    win = LibraryWindow(repo)
    win.show()

    # Note list should have 2 items
    assert win.note_list.count() == 2

    # Verify search
    win.search_input.setText("retry")
    assert win.note_list.count() == 1

    win.search_input.setText("")
    assert win.note_list.count() == 2

    # Select first note (which is n2 because newest first)
    win.note_list.setCurrentRow(0)
    assert win.selected_note.id == "n2"
    assert "GitHub" in win.meta_window_label.text()
    assert "msedge" in win.meta_app_label.text()

    # Select second note (n1)
    win.note_list.setCurrentRow(1)
    assert win.selected_note.id == "n1"

    # Edit transcript
    win.transcript_edit.setPlainText("Fix the connection retry loop immediately")
    assert win.save_btn.isEnabled() is True
    win._save_changes()

    # Verify saved to repo
    updated = repo.get_by_id("n1")
    assert updated.transcript == "Fix the connection retry loop immediately"
    assert updated.original_transcript == "Fix the connection retry loop"

    # Test changing category in details view retrospectively
    idx_task = win.category_combo.findData("Task")
    win.category_combo.setCurrentIndex(idx_task)
    assert repo.get_by_id("n1").category == "Task"
    assert "Task" in win.meta_category_label.text()

    # Test sidebar filtering
    win._on_sidebar_item_clicked("Task")
    assert win.note_list.count() == 1
    assert win._active_filter_category == "Task"

    win._on_sidebar_item_clicked("Bug")
    assert win.note_list.count() == 0

    win._on_sidebar_item_clicked("all")
    assert win.note_list.count() == 2

    # Clean up
    win.close()


def test_overlay_widget_states(qapp, tmp_path: Path):
    from tucknote.config import AppSettings
    from tucknote.ui.overlay import RecordingOverlay

    settings = AppSettings()
    overlay = RecordingOverlay(settings)
    overlay.show()

    # Initial state
    assert overlay._current_state == "ready"
    assert overlay.cancel_btn.isVisible() is False
    assert overlay.copy_btn.isVisible() is False

    # Recording state
    overlay.update_state("recording")
    assert overlay._current_state == "recording"
    assert overlay.cancel_btn.isVisible() is True
    assert "Recording" in overlay.status_label.text()

    # Processing state
    overlay.update_state("processing")
    assert overlay._current_state == "processing"
    assert overlay.cancel_btn.isVisible() is False

    # Saved state with copy button
    overlay.update_state("saved", result_text="Transcribed thought")
    assert overlay._current_state == "saved"
    assert overlay.copy_btn.isVisible() is True
    assert overlay.status_label.text() == "Saved!"

    # Simulate copy click
    copied_signals = []
    overlay.copy_text_requested.connect(copied_signals.append)
    overlay._on_copy_clicked()
    assert len(copied_signals) == 1
    assert copied_signals[0] == "Transcribed thought"

    overlay.close()


def test_library_window_refinement_and_screenshot(qapp, tmp_path: Path):
    from tucknote.config import AppSettings
    db_file = tmp_path / "lib_refine_test.db"
    repo = NoteRepository(db_file)
    settings = AppSettings(refinement_engine="rules")

    dummy_screenshot = tmp_path / "shot.png"
    pix = QPixmap(20, 20)
    pix.fill(Qt.red)
    pix.save(str(dummy_screenshot), "PNG")

    note = Note(
        id="refine-1",
        captured_at_utc="2026-09-27T16:00:00Z",
        transcript="Ich denke ähm die api muss refactored werden",
        screenshot_path=str(dummy_screenshot),
        application="Code.exe",
        window_title="tucknote - Visual Studio Code",
    )
    repo.save(note)

    win = LibraryWindow(repo, settings)
    win.show()

    assert win.note_list.count() == 1
    win.note_list.setCurrentRow(0)

    # Screenshot frame must be visible
    assert win.screenshot_frame.isVisible() is True

    # Test text refinement
    win._run_text_refinement()
    assert "API" in win.processed_edit.toPlainText()
    assert "ähm" not in win.processed_edit.toPlainText()

    # Verify saved to repo
    updated = repo.get_by_id("refine-1")
    assert updated.is_processed is True
    assert "API" in updated.text_processed
    assert updated.category == "Task"  # Heuristic from 'muss' / 'refactored'

    # Test settings panel toggle
    win._on_toggle_settings_bar(True)
    assert win.settings_panel.isVisible() is True

    win.close()


def test_library_window_settings_toggles(qapp, tmp_path: Path):
    from tucknote.config import AppSettings
    db_file = tmp_path / "settings_ui_test.db"
    repo = NoteRepository(db_file)
    settings = AppSettings(overlay_visible=True, show_notifications=True)

    win = LibraryWindow(repo, settings)
    win.show()

    overlay_signals = []
    notif_signals = []
    win.overlay_visibility_toggled.connect(overlay_signals.append)
    win.notifications_enabled_toggled.connect(notif_signals.append)

    # Toggle overlay
    win.overlay_cb.setChecked(False)
    assert win.settings.overlay_visible is False
    assert overlay_signals == [False]

    # Toggle notifications
    win.notifications_cb.setChecked(False)
    assert win.settings.show_notifications is False
    assert notif_signals == [False]

    # Test open_settings helper
    win.open_settings()
    assert win.settings_panel.isVisible() is True
    assert win.toggle_settings_btn.isChecked() is True

    # Test model and language selection
    model_signals = []
    lang_signals = []
    win.whisper_model_changed.connect(model_signals.append)
    win.whisper_language_changed.connect(lang_signals.append)

    win.model_combo.setCurrentIndex(win.model_combo.findData("base"))
    assert win.settings.whisper_model == "base"
    assert model_signals == ["base"]

    win.lang_combo.setCurrentIndex(win.lang_combo.findData("en"))
    assert win.settings.whisper_language == "en"
    assert lang_signals == ["en"]

    # Test refinement engine & llm model combos
    engine_signals = []
    llm_signals = []
    win.refinement_engine_changed.connect(engine_signals.append)
    win.llm_model_changed.connect(llm_signals.append)

    win.engine_combo.setCurrentIndex(win.engine_combo.findData("rules"))
    assert win.settings.refinement_engine == "rules"
    assert engine_signals == ["rules"]

    win.llm_model_combo.setCurrentIndex(win.llm_model_combo.findData("qwen2.5-1.5b"))
    assert win.settings.llm_model == "qwen2.5-1.5b"
    assert llm_signals == ["qwen2.5-1.5b"]

    win.close()

