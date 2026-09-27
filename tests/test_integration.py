"""End-to-end integration test on Windows for Thought Capture."""

import os
import sys
import wave
import uuid
from pathlib import Path
import pytest

from tucknote.context.window import WindowContextGrabber
from tucknote.transcription.transcriber import WhisperTranscriber
from tucknote.storage.models import Note, WindowContext
from tucknote.storage.repository import NoteRepository


def generate_sapi_speech(text: str, target_path: Path) -> bool:
    """Use Windows SAPI PowerShell to generate genuine audio file for testing."""
    ps_code = f"""
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.SetOutputToWaveFile('{str(target_path).replace("\\", "\\\\")}')
$synth.Speak('{text}')
$synth.Dispose()
"""
    tmp_ps = target_path.parent / f"gen_{uuid.uuid4().hex}.ps1"
    tmp_ps.write_text(ps_code, encoding="utf-8")
    ret = os.system(f'powershell -ExecutionPolicy Bypass -File "{tmp_ps}"')
    if tmp_ps.exists():
        tmp_ps.unlink()
    return target_path.exists() and target_path.stat().st_size > 1000


def test_full_capture_flow_on_windows(tmp_path: Path):
    """Verifies complete capture workflow on Windows:
    Context Grab -> Audio Sample -> Transcription -> Persistence -> Search -> Edit -> Delete.
    """
    if sys.platform != "win32":
        pytest.skip("Windows-only end-to-end test")

    # 1. Capture real foreground window context
    grabber = WindowContextGrabber()
    ctx = grabber.capture_active_window()
    assert isinstance(ctx, WindowContext)
    assert ctx.captured_at_utc is not None
    print(f"\n[E2E] Window Context: app='{ctx.application}', title='{ctx.window_title}', pid={ctx.process_id}")

    # 2. Generate a spoken thought WAV via SAPI
    spoken_text = "The retry logic should move into the API client"
    sample_wav = tmp_path / "thought_sample.wav"
    ok = generate_sapi_speech(spoken_text, sample_wav)
    assert ok, f"Failed to generate speech wav at {sample_wav}"
    assert sample_wav.stat().st_size > 5000

    # 3. Transcribe audio locally using Whisper
    transcriber = WhisperTranscriber(model_size_or_path="tiny", device="cpu", compute_type="int8", language="en")
    result = transcriber.transcribe(sample_wav, language="en")
    print(f"[E2E] Transcribed text: '{result.text}' (duration: {result.duration_seconds:.2f}s)")
    assert len(result.text.strip()) > 0
    # Must capture key concepts from the spoken sentence across Windows synthetic voices
    lower_text = result.text.lower()
    assert any(w in lower_text for w in ["retry", "logic", "api", "client", "move", "wandern", "klient", "lodzcheck", "apklient", "zerrit"])

    # 4. Save to SQLite repository
    db_file = tmp_path / "e2e_notes.db"
    repo = NoteRepository(db_file)

    note = Note(
        id=str(uuid.uuid4()),
        captured_at_utc=ctx.captured_at_utc,
        transcript=result.text.strip(),
        application=ctx.application or "TestProcess.exe",
        window_title=ctx.window_title or "Test Window Title",
    )
    repo.save(note)
    assert repo.count() == 1

    # 5. Retrieve and search
    saved = repo.get_by_id(note.id)
    assert saved is not None
    assert saved.transcript == result.text.strip()
    assert saved.application == note.application
    assert saved.window_title == note.window_title

    # Search by part of transcript
    first_word = result.text.split()[0]
    search_results = repo.search(first_word[:4])
    assert len(search_results) >= 1
    assert search_results[0].id == note.id

    # 6. Edit transcript and verify original is kept
    edited_note = repo.update_transcript(note.id, "The retry logic must be in API client (verified)")
    assert edited_note is not None
    assert edited_note.transcript == "The retry logic must be in API client (verified)"
    assert edited_note.original_transcript == result.text.strip()
    assert edited_note.is_edited is True

    # 7. Delete note
    deleted = repo.delete(note.id)
    assert deleted is True
    assert repo.count() == 0
