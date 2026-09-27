"""Tests for SQLite NoteRepository."""

import tempfile
from pathlib import Path
import pytest

from tucknote.storage.models import Note
from tucknote.storage.repository import NoteRepository, CURRENT_SCHEMA_VERSION


@pytest.fixture
def repo(tmp_path: Path):
    db_file = tmp_path / "test_notes.db"
    return NoteRepository(db_file)


def test_init_and_schema_version(repo: NoteRepository):
    with repo._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version;")
        ver = cur.fetchone()[0]
        assert ver == CURRENT_SCHEMA_VERSION


def test_save_and_get_note(repo: NoteRepository):
    note = Note(
        id="test-uuid-1",
        captured_at_utc="2026-09-27T16:00:00+00:00",
        transcript="Die Retry-Logik sollte in den API-Client wandern.",
        application="Code.exe",
        window_title="tucknote - Visual Studio Code",
    )
    repo.save(note)

    fetched = repo.get_by_id("test-uuid-1")
    assert fetched is not None
    assert fetched.id == "test-uuid-1"
    assert fetched.transcript == "Die Retry-Logik sollte in den API-Client wandern."
    assert fetched.application == "Code.exe"
    assert fetched.window_title == "tucknote - Visual Studio Code"
    assert fetched.original_transcript is None


def test_list_all_ordering(repo: NoteRepository):
    n1 = Note(id="1", captured_at_utc="2026-09-27T10:00:00+00:00", transcript="First note")
    n2 = Note(id="2", captured_at_utc="2026-09-27T12:00:00+00:00", transcript="Second note")
    n3 = Note(id="3", captured_at_utc="2026-09-27T11:00:00+00:00", transcript="Middle note")

    repo.save(n1)
    repo.save(n2)
    repo.save(n3)

    notes = repo.list_all()
    assert len(notes) == 3
    # Newest first
    assert [n.id for n in notes] == ["2", "3", "1"]


def test_search_notes(repo: NoteRepository):
    n1 = Note(
        id="1",
        captured_at_utc="2026-09-27T10:00:00+00:00",
        transcript="Refactor database layer",
        application="Code.exe",
        window_title="models.py - tucknote",
    )
    n2 = Note(
        id="2",
        captured_at_utc="2026-09-27T11:00:00+00:00",
        transcript="Research faster-whisper parameters",
        application="msedge.exe",
        window_title="GitHub - SYSTRAN/faster-whisper",
    )
    repo.save(n1)
    repo.save(n2)

    # Search by transcript
    res = repo.search("refactor")
    assert len(res) == 1
    assert res[0].id == "1"

    # Search by app name
    res = repo.search("msedge")
    assert len(res) == 1
    assert res[0].id == "2"

    # Search by window title
    res = repo.search("faster-whisper")
    assert len(res) == 1
    assert res[0].id == "2"

    # Search with empty query returns all
    assert len(repo.search("")) == 2


def test_update_transcript_preserves_original(repo: NoteRepository):
    note = Note(
        id="1",
        captured_at_utc="2026-09-27T10:00:00+00:00",
        transcript="Original spoken thought",
        application="Code.exe",
    )
    repo.save(note)

    updated = repo.update_transcript("1", "Edited spoken thought")
    assert updated is not None
    assert updated.transcript == "Edited spoken thought"
    assert updated.original_transcript == "Original spoken thought"
    assert updated.is_edited is True
    assert updated.updated_at_utc is not None

    # Fetch again from DB
    reloaded = repo.get_by_id("1")
    assert reloaded.transcript == "Edited spoken thought"
    assert reloaded.original_transcript == "Original spoken thought"


def test_delete_note(repo: NoteRepository):
    note = Note(id="del-1", captured_at_utc="2026-09-27T10:00:00+00:00", transcript="To be deleted")
    repo.save(note)
    assert repo.count() == 1

    assert repo.delete("del-1") is True
    assert repo.count() == 0
    assert repo.get_by_id("del-1") is None
    assert repo.delete("non-existent") is False
