"""Tests for UI components (Tray and Library Window) with PySide6."""

import sys
from pathlib import Path
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

    # Clean up
    win.close()
