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


def test_build_default_prompt():
    from tucknote.transcription.transcriber import build_default_prompt
    prompt_de = build_default_prompt(application="Code.exe", window_title="client.py - Visual Studio Code", language="de")
    assert "Antigravity" in prompt_de
    assert "Clipboard" in prompt_de
    assert "Code" in prompt_de
    assert "client.py" in prompt_de

    prompt_en = build_default_prompt(application="msedge.exe", window_title="GitHub Issue", language="en")
    assert "voice note" in prompt_en
    assert "GitHub Issue" in prompt_en


def test_transcribe_samples_empty_and_silent(transcriber: WhisperTranscriber):
    # Empty samples
    res_empty = transcriber.transcribe_samples(np.array([], dtype=np.int16))
    assert res_empty.text == ""

    # Short silence (<0.2s)
    short_silence = np.zeros(2000, dtype=np.int16)
    res_short = transcriber.transcribe_samples(short_silence)
    assert res_short.text == ""

    # 1s silence in-memory
    silence = np.zeros(16000, dtype=np.int16)
    res_silence = transcriber.transcribe_samples(silence)
    assert isinstance(res_silence, TranscriptionResult)
    assert res_silence.text == ""


def test_find_audio_split_point():
    from tucknote.transcription.transcriber import find_audio_split_point

    # Less than min_seconds (2.5s = 40,000 samples)
    short_buf = np.ones(30000, dtype=np.int16) * 500
    assert find_audio_split_point(short_buf) is None

    # 3s buffer with loud signal, no silence at end
    noisy_buf = np.random.randint(-1500, 1500, 48000, dtype=np.int16)
    assert find_audio_split_point(noisy_buf) is None

    # 3s buffer with 350ms silence at end
    silence_ended_buf = noisy_buf.copy()
    silence_ended_buf[-5600:] = 20
    split_pt = find_audio_split_point(silence_ended_buf)
    assert split_pt == 48000

    # Buffer exceeding max_seconds (4.5s = 72,000 samples)
    long_buf = np.random.randint(-1000, 1000, 75000, dtype=np.int16)
    # Valley between 50000 and 52000
    long_buf[50000:52000] = 5
    split_valley = find_audio_split_point(long_buf)
    assert split_valley is not None
    assert 48000 <= split_valley <= 54000


def test_is_whisper_model_cached():
    from tucknote.transcription.transcriber import is_whisper_model_cached

    # tiny is cached because the transcriber fixture loaded it
    assert is_whisper_model_cached("tiny") is True
    # Nonexistent model size returns False
    assert is_whisper_model_cached("nonexistent_model_xyz_99") is False


def test_whisper_model_size_and_deletion(tmp_path: Path, monkeypatch):
    from tucknote.transcription.transcriber import (
        get_whisper_model_dir,
        get_whisper_model_size_mb,
        delete_whisper_model,
        is_whisper_model_cached,
    )

    fake_cache = tmp_path / "hf_cache"
    fake_cache.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HF_HUB_CACHE", str(fake_cache))

    # Initially not cached
    assert is_whisper_model_cached("dummy_test_model") is False
    assert get_whisper_model_size_mb("dummy_test_model") == 0.0

    # Create dummy whisper cache dir
    dummy_model_dir = fake_cache / "models--Systran--faster-whisper-dummy_test_model"
    dummy_model_dir.mkdir(parents=True, exist_ok=True)
    dummy_file = dummy_model_dir / "model.bin"
    dummy_file.write_bytes(b"\x00" * (1024 * 1024 * 2))  # 2 MB

    assert is_whisper_model_cached("dummy_test_model") is True
    assert get_whisper_model_size_mb("dummy_test_model") >= 1.9

    # Delete
    deleted = delete_whisper_model("dummy_test_model")
    assert deleted is True
    assert is_whisper_model_cached("dummy_test_model") is False
    assert dummy_model_dir.exists() is False





