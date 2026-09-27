"""Data models for Thought Capture (tucknote)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class WindowContext:
    """Snapshot of active window context captured at the moment of triggering."""
    application: str | None = None
    window_title: str | None = None
    process_id: int | None = None
    process_path: str | None = None
    captured_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class Note:
    """A captured thought note with context and transcript."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    captured_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    transcript: str = ""
    original_transcript: str | None = None
    application: str | None = None
    window_title: str | None = None
    updated_at_utc: str | None = None

    @property
    def captured_at_local(self) -> datetime:
        """Convert ISO UTC string to local datetime for UI display."""
        try:
            dt = datetime.fromisoformat(self.captured_at_utc)
            return dt.astimezone()
        except Exception:
            return datetime.now()

    @property
    def is_edited(self) -> bool:
        return bool(self.original_transcript and self.original_transcript != self.transcript)
