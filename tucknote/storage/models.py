"""Data models for Thought Capture (tucknote)."""

from __future__ import annotations

import uuid
from pathlib import Path
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
    """A captured thought note with context, original transcript, processed text, and optional screenshot."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    captured_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    transcript: str = ""
    original_transcript: str | None = None
    text_processed: str | None = None
    processed_by: str | None = None
    screenshot_path: str | None = None
    application: str | None = None
    window_title: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    updated_at_utc: str | None = None

    @property
    def transcript_original(self) -> str:
        """Always returns the unadulterated speech-to-text result."""
        return self.original_transcript if self.original_transcript is not None else self.transcript

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
        """True if manual edits were made over the original transcript."""
        return bool(self.original_transcript and self.original_transcript != self.transcript)

    @property
    def is_processed(self) -> bool:
        """True if an automated processed/cleaned text version is available."""
        return bool(self.text_processed and self.text_processed.strip())

    @property
    def has_screenshot(self) -> bool:
        """True if a valid screenshot is attached to this note."""
        if not self.screenshot_path:
            return False
        try:
            return Path(self.screenshot_path).exists()
        except Exception:
            return False

    def display_text(self, version: str = "original") -> str:
        """Return text according to preference ('original' or 'processed')."""
        if version == "processed" and self.is_processed:
            return self.text_processed or self.transcript
        return self.transcript
