"""Tests for AudioRecorder."""

import time
import wave
from pathlib import Path
import numpy as np
import pytest

from tucknote.audio.recorder import AudioRecorder, AudioError, NoMicrophoneError


def test_recorder_initial_state():
    rec = AudioRecorder(sample_rate=16000, max_duration_seconds=120)
    assert rec.is_recording is False
    assert rec.elapsed_seconds == 0.0


def test_recorder_cancel_clears_frames(tmp_path: Path):
    rec = AudioRecorder(sample_rate=16000)
    # Simulate some recorded frames
    rec._frames = [np.zeros(1600, dtype=np.int16)]
    rec._is_recording = True
    rec.cancel()

    assert rec.is_recording is False
    assert len(rec._frames) == 0


def test_recorder_stop_writes_wav(tmp_path: Path):
    rec = AudioRecorder(sample_rate=16000)
    rec._is_recording = True
    # Simulate 0.5s of audio (8000 samples)
    dummy_data = np.ones(8000, dtype=np.int16) * 100
    rec._frames = [dummy_data]

    target = tmp_path / "out.wav"
    saved_path, duration = rec.stop(target)

    assert saved_path == target
    assert target.exists()
    assert duration == pytest.approx(0.5, rel=1e-2)

    with wave.open(str(target), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 8000


def test_recorder_stop_empty(tmp_path: Path):
    rec = AudioRecorder(sample_rate=16000)
    rec._is_recording = True
    rec._frames = []

    target = tmp_path / "empty.wav"
    saved_path, duration = rec.stop(target)
    assert saved_path is None
    assert duration == 0.0
    assert not target.exists()


def test_normalize_audio_frames():
    from tucknote.audio.recorder import normalize_audio_frames
    # Quiet signal with peak 2000
    quiet_signal = np.array([0, 1000, 2000, -1500, 500], dtype=np.int16)
    normalized = normalize_audio_frames(quiet_signal, target_headroom=0.95, max_gain=8.0)
    # Peak should now be amplified
    assert np.max(np.abs(normalized)) > 2000

    # Silent signal (below threshold) should not be amplified
    silent = np.array([0, 10, -10, 5], dtype=np.int16)
    norm_silent = normalize_audio_frames(silent)
    assert np.array_equal(silent, norm_silent)


def test_recorder_streaming_unprocessed_frames():
    rec = AudioRecorder(sample_rate=16000)
    rec._is_recording = True

    # Initially empty
    assert len(rec.get_unprocessed_frames()) == 0

    # Add frame 1
    f1 = np.ones((1600, 1), dtype=np.int16) * 100
    rec._frames.append(f1)
    unprocessed = rec.get_unprocessed_frames()
    assert len(unprocessed) == 1600
    assert np.all(unprocessed == 100)

    # Calling again without new frames returns empty
    assert len(rec.get_unprocessed_frames()) == 0

    # Add frame 2 and frame 3
    f2 = np.ones((800, 1), dtype=np.int16) * 200
    f3 = np.ones((800, 1), dtype=np.int16) * 300
    rec._frames.extend([f2, f3])
    unprocessed2 = rec.get_unprocessed_frames()
    assert len(unprocessed2) == 1600
    assert np.all(unprocessed2[:800] == 200)
    assert np.all(unprocessed2[800:] == 300)


