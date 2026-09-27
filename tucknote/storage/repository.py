"""SQLite persistence layer for Thought Capture notes with schema migrations."""

from __future__ import annotations

import sqlite3
import json
import threading
from pathlib import Path
from datetime import datetime, timezone
import logging

from tucknote.storage.models import Note

logger = logging.getLogger("tucknote")

CURRENT_SCHEMA_VERSION = 3

INIT_SQL_V3 = """
CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    captured_at_utc TEXT NOT NULL,
    transcript TEXT NOT NULL,
    original_transcript TEXT,
    text_processed TEXT,
    processed_by TEXT,
    screenshot_path TEXT,
    application TEXT,
    window_title TEXT,
    category TEXT,
    tags TEXT,
    updated_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_notes_captured_at ON notes(captured_at_utc DESC);
CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);
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
            cur = conn.cursor()
            cur.execute("PRAGMA user_version;")
            version = cur.fetchone()[0]

            if version == 0:
                cur.executescript(INIT_SQL_V3)
                cur.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION};")
                conn.commit()
            else:
                if version < 2:
                    logger.info("Migrating SQLite schema from version 1 to 2...")
                    for col in ["text_processed", "processed_by", "screenshot_path"]:
                        try:
                            cur.execute(f"ALTER TABLE notes ADD COLUMN {col} TEXT;")
                        except sqlite3.OperationalError:
                            pass
                if version < 3:
                    logger.info("Migrating SQLite schema to version 3 (category, tags)...")
                    for col in ["category", "tags"]:
                        try:
                            cur.execute(f"ALTER TABLE notes ADD COLUMN {col} TEXT;")
                        except sqlite3.OperationalError:
                            pass
                    try:
                        cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);")
                    except sqlite3.OperationalError:
                        pass
                cur.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION};")
                conn.commit()

    def save(self, note: Note) -> Note:
        """Insert or replace a note in the database."""
        tags_json = json.dumps(note.tags) if note.tags else None
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO notes (
                    id, captured_at_utc, transcript, original_transcript,
                    text_processed, processed_by, screenshot_path,
                    application, window_title, category, tags, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    transcript = excluded.transcript,
                    original_transcript = COALESCE(notes.original_transcript, excluded.original_transcript),
                    text_processed = COALESCE(excluded.text_processed, notes.text_processed),
                    processed_by = COALESCE(excluded.processed_by, notes.processed_by),
                    screenshot_path = COALESCE(excluded.screenshot_path, notes.screenshot_path),
                    application = excluded.application,
                    window_title = excluded.window_title,
                    category = COALESCE(excluded.category, notes.category),
                    tags = COALESCE(excluded.tags, notes.tags),
                    updated_at_utc = excluded.updated_at_utc;
                """,
                (
                    note.id,
                    note.captured_at_utc,
                    note.transcript,
                    note.original_transcript,
                    note.text_processed,
                    note.processed_by,
                    note.screenshot_path,
                    note.application,
                    note.window_title,
                    note.category,
                    tags_json,
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

    def update_processed_text(
        self,
        note_id: str,
        text_processed: str,
        processed_by: str = "local",
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> Note | None:
        """Set or update the processed/cleaned text version of a note without overwriting original."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return None

            note = self._row_to_note(row)
            note.text_processed = text_processed
            note.processed_by = processed_by
            if category is not None:
                note.category = category
            if tags is not None:
                note.tags = tags
            note.updated_at_utc = datetime.now(timezone.utc).isoformat()
            tags_json = json.dumps(note.tags) if note.tags else None

            cur.execute(
                """
                UPDATE notes SET
                    text_processed = ?,
                    processed_by = ?,
                    category = ?,
                    tags = ?,
                    updated_at_utc = ?
                WHERE id = ?;
                """,
                (note.text_processed, note.processed_by, note.category, tags_json, note.updated_at_utc, note_id),
            )
            conn.commit()
            return note

    def attach_screenshot(self, note_id: str, screenshot_path: str) -> Note | None:
        """Attach a screenshot path to an existing note."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return None

            now_utc = datetime.now(timezone.utc).isoformat()
            cur.execute(
                """
                UPDATE notes SET
                    screenshot_path = ?,
                    updated_at_utc = ?
                WHERE id = ?;
                """,
                (str(screenshot_path), now_utc, note_id),
            )
            conn.commit()
            note = self._row_to_note(row)
            note.screenshot_path = str(screenshot_path)
            note.updated_at_utc = now_utc
            return note

    def remove_screenshot(self, note_id: str) -> bool:
        """Remove screenshot from note and delete file from disk."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT screenshot_path FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return False

            old_path = row["screenshot_path"]
            if old_path:
                try:
                    p = Path(old_path)
                    if p.exists():
                        p.unlink()
                except Exception as e:
                    logger.debug("Failed deleting screenshot file: %s", e)

            cur.execute(
                "UPDATE notes SET screenshot_path = NULL, updated_at_utc = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), note_id),
            )
            conn.commit()
            return True

    def delete(self, note_id: str) -> bool:
        """Delete a note by ID and remove its screenshot file if present."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            # Check for screenshot file to delete
            cur.execute("SELECT screenshot_path FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if row and row["screenshot_path"]:
                try:
                    p = Path(row["screenshot_path"])
                    if p.exists():
                        p.unlink()
                        logger.info("Deleted screenshot for note %s: %s", note_id, p.name)
                except Exception as e:
                    logger.debug("Failed deleting screenshot on note deletion: %s", e)

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

    def update_category(self, note_id: str, category: str | None) -> Note | None:
        """Update the category of an existing note."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return None

            note = self._row_to_note(row)
            note.category = category
            note.updated_at_utc = datetime.now(timezone.utc).isoformat()

            cur.execute(
                """
                UPDATE notes SET
                    category = ?,
                    updated_at_utc = ?
                WHERE id = ?;
                """,
                (note.category, note.updated_at_utc, note_id),
            )
            conn.commit()
            return note

    def update_tags(self, note_id: str, tags: list[str]) -> Note | None:
        """Update the tags of an existing note."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
            row = cur.fetchone()
            if not row:
                return None

            note = self._row_to_note(row)
            note.tags = tags
            note.updated_at_utc = datetime.now(timezone.utc).isoformat()
            tags_json = json.dumps(note.tags) if note.tags else None

            cur.execute(
                """
                UPDATE notes SET
                    tags = ?,
                    updated_at_utc = ?
                WHERE id = ?;
                """,
                (tags_json, note.updated_at_utc, note_id),
            )
            conn.commit()
            return note

    def get_category_counts(self) -> dict[str, int]:
        """Return counts of notes per category and attachment status."""
        counts = {
            "all": 0,
            "Task": 0,
            "Bug": 0,
            "Idea": 0,
            "Note": 0,
            "screenshot": 0,
        }
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM notes;")
            counts["all"] = cur.fetchone()[0]

            cur.execute("SELECT category, COUNT(*) FROM notes WHERE category IS NOT NULL GROUP BY category;")
            for cat, c in cur.fetchall():
                if cat in counts:
                    counts[cat] = c

            cur.execute("SELECT COUNT(*) FROM notes WHERE screenshot_path IS NOT NULL AND screenshot_path != '';")
            counts["screenshot"] = cur.fetchone()[0]
        return counts

    def search(
        self,
        query: str = "",
        category: str | None = None,
        has_screenshot: bool | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Note]:
        """Search notes with optional category and screenshot filtering."""
        query_strip = query.strip()
        conditions: list[str] = []
        params: list[object] = []

        if query_strip:
            like_pattern = f"%{query_strip}%"
            conditions.append(
                """(transcript LIKE ? ESCAPE '\\'
                    OR text_processed LIKE ? ESCAPE '\\'
                    OR application LIKE ? ESCAPE '\\'
                    OR window_title LIKE ? ESCAPE '\\'
                    OR category LIKE ? ESCAPE '\\'
                    OR tags LIKE ? ESCAPE '\\')"""
            )
            params.extend([like_pattern] * 6)

        if category is not None:
            conditions.append("category = ?")
            params.append(category)

        if has_screenshot is True:
            conditions.append("screenshot_path IS NOT NULL AND screenshot_path != ''")
        elif has_screenshot is False:
            conditions.append("(screenshot_path IS NULL OR screenshot_path = '')")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT * FROM notes
            {where_clause}
            ORDER BY captured_at_utc DESC
            LIMIT ? OFFSET ?;
        """
        params.extend([limit, offset])

        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(sql, params)
            return [self._row_to_note(row) for row in cur.fetchall()]

    def count(self) -> int:
        """Return total number of notes."""
        with self._lock, self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM notes;")
            return cur.fetchone()[0]

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> Note:
        keys = row.keys()
        tags_raw = row["tags"] if "tags" in keys else None
        tags = []
        if tags_raw:
            try:
                tags = json.loads(tags_raw)
            except Exception:
                tags = [tags_raw]

        return Note(
            id=row["id"],
            captured_at_utc=row["captured_at_utc"],
            transcript=row["transcript"],
            original_transcript=row["original_transcript"],
            text_processed=row["text_processed"] if "text_processed" in keys else None,
            processed_by=row["processed_by"] if "processed_by" in keys else None,
            screenshot_path=row["screenshot_path"] if "screenshot_path" in keys else None,
            application=row["application"],
            window_title=row["window_title"],
            category=row["category"] if "category" in keys else None,
            tags=tags,
            updated_at_utc=row["updated_at_utc"],
        )
