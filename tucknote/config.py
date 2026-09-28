"""Configuration, paths, settings persistence and constants for Thought Capture (tucknote)."""

from __future__ import annotations

import os
import sys
import json
import logging
from pathlib import Path
from dataclasses import dataclass, asdict, field

APP_NAME = "tucknote"
APP_DISPLAY_NAME = "Tucknote"
APP_VERSION = "0.2.0"

# Directories
def get_data_dir() -> Path:
    custom_dir = os.environ.get("TUCKNOTE_DATA_DIR")
    if custom_dir:
        path = Path(custom_dir)
    elif sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local_app_data:
            path = Path(local_app_data) / APP_NAME
        else:
            path = Path.home() / f".{APP_NAME}"
    else:
        path = Path.home() / f".{APP_NAME}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_db_path() -> Path:
    return get_data_dir() / "notes.db"


def get_temp_audio_dir() -> Path:
    path = get_data_dir() / "temp_audio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_screenshots_dir() -> Path:
    path = get_data_dir() / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    path = get_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_settings_path() -> Path:
    return get_data_dir() / "settings.json"


@dataclass
class AppSettings:
    """User-configurable settings persisted to settings.json."""
    auto_copy_clipboard: bool = False
    default_text_version: str = "original"  # "original" or "processed"
    overlay_visible: bool = True
    show_notifications: bool = True
    overlay_x: int | None = None
    overlay_y: int | None = None
    whisper_model: str = "small"
    whisper_language: str = "de"  # "de", "en", or "auto"
    hotkey_str: str = "Ctrl+Alt+Space"
    refinement_engine: str = "llm"  # "llm" or "rules"
    llm_model: str = "qwen2.5-0.5b"  # "qwen2.5-0.5b" or "qwen2.5-1.5b"
    streaming_transcription: bool = False  # Transcribe speech chunks in background while recording

    @classmethod
    def load(cls) -> AppSettings:
        path = get_settings_path()
        if not path.exists():
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            model = str(data.get("whisper_model", "small"))
            if model == "base":
                model = "small"
            return cls(
                auto_copy_clipboard=bool(data.get("auto_copy_clipboard", False)),
                default_text_version=str(data.get("default_text_version", "original")),
                overlay_visible=bool(data.get("overlay_visible", True)),
                show_notifications=bool(data.get("show_notifications", True)),
                overlay_x=data.get("overlay_x"),
                overlay_y=data.get("overlay_y"),
                whisper_model=model,
                whisper_language=str(data.get("whisper_language", "de")),
                hotkey_str=str(data.get("hotkey_str", "Ctrl+Alt+Space")),
                refinement_engine=str(data.get("refinement_engine", "llm")),
                llm_model=str(data.get("llm_model", "qwen2.5-0.5b")),
                streaming_transcription=bool(data.get("streaming_transcription", False)),
            )
        except Exception as e:
            logger = logging.getLogger(APP_NAME)
            logger.warning("Could not read settings from %s, using defaults: %s", path, e)
            return cls()

    def save(self) -> None:
        path = get_settings_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, indent=2)
        except Exception as e:
            logger = logging.getLogger(APP_NAME)
            logger.warning("Could not save settings to %s: %s", path, e)


@dataclass
class AppConfig:
    # Audio
    sample_rate: int = 16000
    channels: int = 1
    max_recording_seconds: int = 120  # 2 minutes max note
    silence_threshold_energy: float = 0.001

    # Transcription
    whisper_model: str = os.environ.get("TUCKNOTE_WHISPER_MODEL", "small")
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = "de"  # default "de" (best for Denglisch)

    # Hotkey (default: Ctrl+Alt+Space)
    hotkey_str: str = "Ctrl+Alt+Space"
    hotkey_key: str = "Space"
    hotkey_modifiers: tuple[str, ...] = ("Ctrl", "Alt")

    # Settings
    settings: AppSettings = field(default_factory=AppSettings.load)

    # Logging
    log_level: int = logging.INFO


def setup_logging(config: AppConfig | None = None) -> logging.Logger:
    """Setup structured application logging.
    
    IMPORTANT: As per privacy specification, logger MUST NEVER log spoken transcripts or raw audio data!
    """
    logger = logging.getLogger(APP_NAME)
    if not logger.handlers:
        level = config.log_level if config else logging.INFO
        logger.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File handler
        try:
            log_file = get_logs_dir() / "tucknote.log"
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception:
            pass  # Fall back to console only if file cannot be opened

    return logger
