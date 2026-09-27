"""SQLite persistence layer for Thought Capture notes."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone
from typing import Sequence

from tucknote.storage.models import Note

CURRENT_SCHEMA_VERSION = 1

INIT_SQL = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    captured_at_utc TEXT NOT NULL,
    transcript TEXT NOT NULL,
    original_transcript TEXT,
    application TEXT,
    window_title TEXT,
    updated_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_captured_at ON notes(captured_at_utc DESC);
"""


class NoteRepository:
    """Manages SQLite storage for captured notes with migrations and thread safety."""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            # Check user_version for migration support
            cur = conn.cursor()
            cur.execute("PRAGMA user_version;")
            version = cur.fetchone()[0]

            if version == 0:
                cur.executescript(INIT_SQL)
                cur.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION};")
                conn.commit()

    def save(self, note: Note) -> Note:
        """Insert or replace a note in the database."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO notes (
                    id, captured_at_utc, transcript, original_transcript,
                    application, window_title, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    transcript = excluded.transcript,
                    original_transcript = COALESCE(notes.original_transcript, excluded.original_transcript),
                    application = excluded.application,
                    window_title = excluded.window_title,
                    updated_at_utc = excluded.updated_at_utc;
                """,
                (
                    note.id,
                    note.captured_at_utc,
                    note.transcript,
                    note.original_transcript,
                    note.application,
                    note.window_title,
                    note.updated_at_utc,
                ),
            )
            conn.commit()
        return note

    def update_transcript(self, note_id: str, new_transcript: str) -> Note | None:
        """Update a note's transcript text while preserving the original transcript."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return None

            note = self._row_to_note(row)
            if note.original_transcript is None:
                note.original_transcript = note.transcript
            note.transcript = new_transcript
            note.updated_at_utc = datetime.now(timezone.utc).isoformat()

            cur.execute(
                """
                UPDATE notes SET
                    transcript = ?,
                    original_transcript = ?,
                    updated_at_utc = ?
                WHERE id = ?;
                """,
                (note.transcript, note.original_transcript, note.updated_at_utc, note_id),
            )
            conn.commit()
            return note

    def delete(self, note_id: str) -> bool:
        """Delete a note by ID."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_by_id(self, note_id: str) -> Note | None:
        """Fetch a single note by ID."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if row:
                return self._row_to_note(row)
            return None

    def list_all(self, limit: int = 200, offset: int = 0) -> list[Note]:
        """List notes chronologically, newest first."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM notes
                ORDER BY captured_at_utc DESC
                LIMIT ? OFFSET ?;
                """,
                (limit, offset),
            )
            return [self._row_to_note(row) for row in cur.fetchall()]

    def search(self, query: str, limit: int = 200, offset: int = 0) -> list[Note]:
        """Case-insensitive substring search across transcript, app name, and window title."""
        query_strip = query.strip()
        if not query_strip:
            return self.list_all(limit=limit, offset=offset)

        like_pattern = f"%{query_strip}%"
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM notes
                WHERE transcript LIKE ? ESCAPE '\\'
                   OR application LIKE ? ESCAPE '\\'
                   OR window_title LIKE ? ESCAPE '\\'
                ORDER BY captured_at_utc DESC
                LIMIT ? OFFSET ?;
                """,
                (like_pattern, like_pattern, like_pattern, limit, offset),
            )
            return [self._row_to_note(row) for row in cur.fetchall()]

    def count(self) -> int:
        """Return total number of notes."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM notes;")
            return cur.fetchone()[0]

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> Note:
        return Note(
            id=row["id"],
            captured_at_utc=row["captured_at_utc"],
            transcript=row["transcript"],
            original_transcript=row["original_transcript"],
            application=row["application"],
            window_title=row["window_title"],
            updated_at_utc=row["updated_at_utc"],
        )
