"""Tests for WhisperTranscriber."""

import wave
from pathlib import Path
import numpy as np
import pytest

from tucknote.transcription.transcriber import WhisperTranscriber, TranscriptionResult


@pytest.fixture(scope="module")
def transcriber():
    # Use tiny model for quick test execution
    t = WhisperTranscriber(model_size_or_path="tiny", device="cpu", compute_type="int8")
    t.load_model()
    return t


def test_transcriber_is_loaded(transcriber: WhisperTranscriber):
    assert transcriber.is_loaded is True


def test_transcribe_empty_file(transcriber: WhisperTranscriber, tmp_path: Path):
    empty_file = tmp_path / "tiny_empty.wav"
    empty_file.write_bytes(b"RIFF" + b"\x00" * 40)  # corrupt/empty header
    res = transcriber.transcribe(empty_file)
    assert res.text == ""


def test_transcribe_nonexistent_file(transcriber: WhisperTranscriber, tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        transcriber.transcribe(tmp_path / "does_not_exist.wav")


def test_transcribe_silent_wav(transcriber: WhisperTranscriber, tmp_path: Path):
    wav_path = tmp_path / "silence.wav"
    # Create 1s of 16kHz silence
    data = np.zeros(16000, dtype=np.int16)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(data.tobytes())

    res = transcriber.transcribe(wav_path)
    assert isinstance(res, TranscriptionResult)
    # VAD filter filters out pure silence -> empty text
    assert res.text == ""
