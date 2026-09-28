"""Tests for AppSettings persistence."""

import json
from pathlib import Path
from tucknote.config import AppSettings, get_settings_path


def test_settings_defaults():
    s = AppSettings()
    assert s.auto_copy_clipboard is False
    assert s.default_text_version == "original"
    assert s.overlay_visible is True
    assert s.show_notifications is True
    assert s.whisper_model == "small"
    assert s.whisper_language == "de"
    assert s.refinement_engine == "llm"
    assert s.llm_model == "qwen2.5-0.5b"
    assert s.streaming_transcription is False


def test_settings_save_and_load(tmp_path: Path, monkeypatch):
    test_json = tmp_path / "test_settings.json"
    monkeypatch.setattr("tucknote.config.get_settings_path", lambda: test_json)

    s = AppSettings(
        auto_copy_clipboard=True,
        default_text_version="processed",
        overlay_visible=False,
        show_notifications=False,
        whisper_model="medium",
        whisper_language="en",
        refinement_engine="rules",
        llm_model="qwen2.5-1.5b",
        streaming_transcription=True,
        overlay_x=250,
        overlay_y=120,
    )
    s.save()
    assert test_json.exists()

    loaded = AppSettings.load()
    assert loaded.auto_copy_clipboard is True
    assert loaded.default_text_version == "processed"
    assert loaded.overlay_visible is False
    assert loaded.show_notifications is False
    assert loaded.whisper_model == "medium"
    assert loaded.whisper_language == "en"
    assert loaded.refinement_engine == "rules"
    assert loaded.llm_model == "qwen2.5-1.5b"
    assert loaded.streaming_transcription is True
    assert loaded.overlay_x == 250
    assert loaded.overlay_y == 120
