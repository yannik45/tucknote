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


def test_schema_v1_to_v2_migration(tmp_path: Path):
    import sqlite3
    db_file = tmp_path / "v1_legacy.db"

    # Create v1 schema manually
    with sqlite3.connect(str(db_file)) as conn:
        conn.executescript(
            """
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                captured_at_utc TEXT NOT NULL,
                transcript TEXT NOT NULL,
                original_transcript TEXT,
                application TEXT,
                window_title TEXT,
                updated_at_utc TEXT
            );
            PRAGMA user_version = 1;
            """
        )
        conn.execute(
            "INSERT INTO notes (id, captured_at_utc, transcript) VALUES ('old-1', '2026-09-27T00:00:00Z', 'Legacy note');"
        )
        conn.commit()

    # Open with NoteRepository -> should trigger migration to v3
    repo = NoteRepository(db_file)
    with repo._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version;")
        assert cur.fetchone()[0] == 3

    # Verify old note is preserved and has new fields as None/empty
    old_note = repo.get_by_id("old-1")
    assert old_note is not None
    assert old_note.transcript == "Legacy note"
    assert old_note.text_processed is None
    assert old_note.screenshot_path is None
    assert old_note.category is None
    assert old_note.tags == []


def test_schema_v2_to_v3_migration(tmp_path: Path):
    import sqlite3
    db_file = tmp_path / "v2_legacy.db"

    # Create v2 schema manually
    with sqlite3.connect(str(db_file)) as conn:
        conn.executescript(
            """
            CREATE TABLE notes (
                id TEXT PRIMARY KEY,
                captured_at_utc TEXT NOT NULL,
                transcript TEXT NOT NULL,
                original_transcript TEXT,
                text_processed TEXT,
                processed_by TEXT,
                screenshot_path TEXT,
                application TEXT,
                window_title TEXT,
                updated_at_utc TEXT
            );
            PRAGMA user_version = 2;
            """
        )
        conn.execute(
            "INSERT INTO notes (id, captured_at_utc, transcript) VALUES ('v2-1', '2026-09-27T00:00:00Z', 'V2 note');"
        )
        conn.commit()

    repo = NoteRepository(db_file)
    with repo._get_connection() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA user_version;")
        assert cur.fetchone()[0] == 3

    v2_note = repo.get_by_id("v2-1")
    assert v2_note is not None
    assert v2_note.category is None
    assert v2_note.tags == []


def test_note_with_category_and_tags(repo: NoteRepository):
    note = Note(
        id="cat-1",
        captured_at_utc="2026-09-27T12:00:00Z",
        transcript="Fix database connection leak",
        text_processed="Fix the database connection leak.",
        category="Bug",
        tags=["database", "leak", "backend"],
        application="Code.exe",
    )
    repo.save(note)

    fetched = repo.get_by_id("cat-1")
    assert fetched is not None
    assert fetched.category == "Bug"
    assert fetched.tags == ["database", "leak", "backend"]

    # Search by tag
    res_tag = repo.search("backend")
    assert len(res_tag) == 1
    assert res_tag[0].id == "cat-1"

    # Search by category
    res_cat = repo.search("Bug")
    assert len(res_cat) == 1
    assert res_cat[0].id == "cat-1"

    # Update category and tags
    updated = repo.update_processed_text(
        "cat-1",
        "Updated text",
        category="Task",
        tags=["database", "resolved"],
    )
    assert updated.category == "Task"
    assert updated.tags == ["database", "resolved"]

    refetched = repo.get_by_id("cat-1")
    assert refetched.category == "Task"
    assert refetched.tags == ["database", "resolved"]


def test_note_with_screenshot_and_processing(repo: NoteRepository, tmp_path: Path):
    dummy_screenshot = tmp_path / "dummy_screen.png"
    dummy_screenshot.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)

    note = Note(
        id="ss-1",
        captured_at_utc="2026-09-27T12:00:00Z",
        transcript="Spoken with screenshot",
        text_processed="Spoken with screenshot (refined).",
        processed_by="rule-based-v1",
        screenshot_path=str(dummy_screenshot),
        application="Code.exe",
    )
    repo.save(note)

    fetched = repo.get_by_id("ss-1")
    assert fetched is not None
    assert fetched.text_processed == "Spoken with screenshot (refined)."
    assert fetched.processed_by == "rule-based-v1"
    assert fetched.screenshot_path == str(dummy_screenshot)
    assert fetched.has_screenshot is True

    # Search by processed text
    res = repo.search("refined")
    assert len(res) == 1
    assert res[0].id == "ss-1"

    # Deleting note must also remove screenshot file from disk
    assert dummy_screenshot.exists()
    repo.delete("ss-1")
    assert not dummy_screenshot.exists()


def test_update_category_and_counts(repo: NoteRepository):
    n1 = Note(id="c-1", captured_at_utc="2026-09-27T01:00:00Z", transcript="Task 1", category="Task")
    n2 = Note(id="c-2", captured_at_utc="2026-09-27T02:00:00Z", transcript="Bug 1", category="Bug")
    n3 = Note(id="c-3", captured_at_utc="2026-09-27T03:00:00Z", transcript="No category", category=None)
    repo.save(n1)
    repo.save(n2)
    repo.save(n3)

    counts = repo.get_category_counts()
    assert counts["Task"] >= 1
    assert counts["Bug"] >= 1

    # Update category directly
    updated = repo.update_category("c-3", "Idea")
    assert updated is not None
    assert updated.category == "Idea"

    refetched = repo.get_by_id("c-3")
    assert refetched.category == "Idea"

    # Search by category
    tasks = repo.search(category="Task")
    assert any(n.id == "c-1" for n in tasks)
    assert not any(n.id == "c-2" for n in tasks)

    # Search with query + category
    filtered = repo.search(query="Task 1", category="Task")
    assert len(filtered) == 1
    assert filtered[0].id == "c-1"
