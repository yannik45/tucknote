"""Configuration and constants for Thought Capture (tucknote)."""

from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from dataclasses import dataclass

APP_NAME = "tucknote"
APP_DISPLAY_NAME = "Thought Capture"
APP_VERSION = "0.1.0"

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


def get_logs_dir() -> Path:
    path = get_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppConfig:
    # Audio
    sample_rate: int = 16000
    channels: int = 1
    max_recording_seconds: int = 120  # 2 minutes max note
    silence_threshold_energy: float = 0.001

    # Transcription
    whisper_model: str = os.environ.get("TUCKNOTE_WHISPER_MODEL", "base")
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_language: str | None = None  # None = auto-detect de, en, etc.

    # Hotkey (default: Ctrl+Alt+Space)
    hotkey_str: str = "Ctrl+Alt+Space"
    hotkey_key: str = "Space"
    hotkey_modifiers: tuple[str, ...] = ("Ctrl", "Alt")

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
