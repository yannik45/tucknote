"""Tests for StreamingTranscriptionSession."""

import time
import numpy as np
import pytest
from unittest.mock import MagicMock

from tucknote.transcription.streaming import StreamingTranscriptionSession
from tucknote.transcription.transcriber import TranscriptionResult


def test_streaming_session_init_and_cancel():
    mock_rec = MagicMock()
    mock_rec.get_unprocessed_frames.return_value = np.array([], dtype=np.int16)
    mock_transcriber = MagicMock()

    session = StreamingTranscriptionSession(
        recorder=mock_rec,
        transcriber=mock_transcriber,
        initial_prompt="Test prompt",
        language="de",
    )
    session.start()
    assert session._thread is not None
    assert session._thread.is_alive()

    session.cancel()
    assert len(session._buffer) == 0
    assert len(session._segments) == 0


def test_streaming_session_finish_with_tail():
    mock_rec = MagicMock()
    mock_rec.get_unprocessed_frames.return_value = np.array([], dtype=np.int16)
    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_samples.return_value = TranscriptionResult(text="Hallo Welt")

    session = StreamingTranscriptionSession(
        recorder=mock_rec,
        transcriber=mock_transcriber,
        initial_prompt="Prompt",
        language="de",
    )
    # Preload a 0.5s audio tail (8000 samples)
    session._buffer = np.ones(8000, dtype=np.int16) * 100

    full_text = session.finish()
    assert full_text == "Hallo Welt"
    mock_transcriber.transcribe_samples.assert_called_once()


def test_streaming_session_chunks_and_callback():
    mock_rec = MagicMock()
    # Return 3s audio with 350ms silence at end
    audio_chunk = np.random.randint(-1500, 1500, 48000, dtype=np.int16)
    audio_chunk[-5600:] = 20
    # First call returns chunk, subsequent calls return empty
    mock_rec.get_unprocessed_frames.side_effect = [audio_chunk, np.array([], dtype=np.int16), np.array([], dtype=np.int16)]

    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_samples.return_value = TranscriptionResult(text="Erster Satz.")

    callbacks = []
    def on_chunk(chunk, full):
        callbacks.append((chunk, full))

    session = StreamingTranscriptionSession(
        recorder=mock_rec,
        transcriber=mock_transcriber,
        initial_prompt="Prompt",
        language="de",
        on_chunk_transcribed=on_chunk,
    )
    session.start()

    # Wait briefly for worker thread to process the chunk
    time.sleep(0.4)

    full_text = session.finish()
    assert "Erster Satz." in full_text
    assert len(callbacks) >= 1
    assert callbacks[0] == ("Erster Satz.", "Erster Satz.")


def test_join_transcription_segments():
    from tucknote.transcription.streaming import join_transcription_segments

    # Normal join
    assert join_transcription_segments(["Hallo Welt", "wie gehts"]) == "Hallo Welt wie gehts"

    # Boundary word deduplication
    assert join_transcription_segments(["Hier ist ein Bug,", "Bug fixen"]) == "Hier ist ein Bug, fixen"

    # Empty segments
    assert join_transcription_segments([]) == ""
    assert join_transcription_segments(["", "   ", "Test"]) == "Test"


def test_streaming_finish_with_full_audio():
    mock_rec = MagicMock()
    mock_transcriber = MagicMock()
    mock_transcriber.transcribe_samples.side_effect = [
        TranscriptionResult(text="Tail Satz.")
    ]

    session = StreamingTranscriptionSession(
        recorder=mock_rec,
        transcriber=mock_transcriber,
        initial_prompt="Prompt",
        language="de",
    )
    # Simulate Chunk 1 already transcribed (40,000 samples)
    session._segments = ["Erster Chunk."]
    session._processed_samples = 40000

    # Total audio was 64,000 samples (24,000 samples in tail = 1.5s)
    full_audio = np.ones(64000, dtype=np.int16) * 100

    result = session.finish(full_audio=full_audio)
    assert result == "Erster Chunk. Tail Satz."
    # transcribe_samples called with the 24,000-sample tail
    mock_transcriber.transcribe_samples.assert_called_once()
    args, kwargs = mock_transcriber.transcribe_samples.call_args
    assert len(args[0]) == 24000

