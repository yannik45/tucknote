"""Local speech-to-text transcription engine using faster-whisper."""

from __future__ import annotations

import os
import time
import logging
import threading
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger("tucknote")


@dataclass
class TranscriptionResult:
    text: str
    language: str | None = None
    language_probability: float = 0.0
    duration_seconds: float = 0.0
    inference_time_seconds: float = 0.0


class TranscriptionError(Exception):
    """Raised when transcription fails."""
    pass


def build_default_prompt(
    application: str | None = None,
    window_title: str | None = None,
    language: str | None = "de",
) -> str:
    """Build vocabulary-rich initial prompt for Whisper to guide decoding of tech terminology."""
    parts = []
    if language == "en":
        parts.append(
            "Thought Capture voice note with technical terms: "
            "Antigravity, recording, clipboard, save, check, feature, issue, branch, "
            "commit, repository, pull request, frontend, backend, UI, bug, API, VS Code, Git."
        )
    else:
        # German or Auto / Denglisch
        parts.append(
            "Thought Capture Sprachnotiz auf Deutsch mit Fachbegriffen und Denglisch: "
            "Antigravity, Recording, Clipboard, saven, checken, Feature, Issue, Branch, "
            "Commit, Repository, Pull Request, Frontend, Backend, UI, Bug, API, VS Code, Git."
        )

    context_hints = []
    if application:
        context_hints.append(application.replace(".exe", "").strip())
    if window_title:
        title = window_title.strip()
        if len(title) > 60:
            title = title[:57] + "..."
        context_hints.append(title)

    if context_hints:
        parts.append("Aktiver Kontext: " + " — ".join(context_hints) + ".")

    return " ".join(parts)


class WhisperTranscriber:
    """Manages the faster-whisper model instance and runs local audio transcription."""

    def __init__(
        self,
        model_size_or_path: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str | None = None,
    ):
        self.model_size_or_path = model_size_or_path
        self.device = device
        self.compute_type = compute_type
        self.language = None if language == "auto" else language

        self._model = None
        self._lock = threading.Lock()
        self._is_loading = False

    def update_config(self, model_size_or_path: str | None = None, language: str | None = None) -> None:
        """Update model size or language dynamically with zero-downtime hot-reloading."""
        target_model = None
        with self._lock:
            if model_size_or_path and model_size_or_path != self.model_size_or_path:
                target_model = model_size_or_path
            if language is not None:
                self.language = None if language == "auto" else language

        if target_model:
            def _bg_worker():
                try:
                    logger.info("Downloading/loading Whisper model '%s' in background...", target_model)
                    from faster_whisper import WhisperModel
                    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                    cpu_threads = min(8, os.cpu_count() or 4)
                    new_model = WhisperModel(
                        target_model,
                        device=self.device,
                        compute_type=self.compute_type,
                        cpu_threads=cpu_threads,
                    )
                    with self._lock:
                        self._model = new_model
                        self.model_size_or_path = target_model
                    logger.info("Whisper model '%s' is now loaded and active.", target_model)
                except Exception as e:
                    logger.error("Failed to load model '%s': %s", target_model, e)

            threading.Thread(target=_bg_worker, daemon=True).start()

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._model is not None

    def load_model(self) -> None:
        """Explicitly preload the model if not already loaded."""
        with self._lock:
            if self._model is not None:
                return

        self._ensure_model_loaded()

    def _ensure_model_loaded(self):
        with self._lock:
            if self._model is not None:
                return self._model

            from faster_whisper import WhisperModel

            logger.info(
                "Loading faster-whisper model '%s' (device=%s, compute_type=%s)...",
                self.model_size_or_path,
                self.device,
                self.compute_type,
            )
            t0 = time.time()
            try:
                # Disables huggingface symlink warnings if needed
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                cpu_threads = min(8, os.cpu_count() or 4)
                self._model = WhisperModel(
                    self.model_size_or_path,
                    device=self.device,
                    compute_type=self.compute_type,
                    cpu_threads=cpu_threads,
                )
                t1 = time.time()
                logger.info(
                    "faster-whisper model '%s' loaded in %.2fs (threads=%d).",
                    self.model_size_or_path,
                    t1 - t0,
                    cpu_threads,
                )
            except Exception as e:
                logger.error("Failed loading faster-whisper model: %s", e)
                raise TranscriptionError(f"Could not load Whisper model: {e}") from e

            return self._model

    def transcribe(
        self,
        wav_path: Path | str,
        initial_prompt: str | None = None,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file locally.
        
        Returns TranscriptionResult. Never logs the transcribed text for privacy.
        """
        wav_file = Path(wav_path)
        if not wav_file.exists():
            raise FileNotFoundError(f"Audio file does not exist: {wav_file}")

        file_size = wav_file.stat().st_size
        if file_size < 100:  # Header-only or empty WAV
            return TranscriptionResult(text="")

        model = self._ensure_model_loaded()

        logger.info("Transcribing audio file (%d bytes)...", file_size)
        t0 = time.time()

        try:
            # Determine language parameter
            effective_lang = self.language if language is None else (None if language == "auto" else language)

            # High-performance greedy decoding with zero latency overhead
            kwargs = {
                "beam_size": 1,
                "temperature": 0.0,
                "condition_on_previous_text": False,
                "without_timestamps": True,
            }
            if effective_lang:
                kwargs["language"] = effective_lang
            if initial_prompt:
                kwargs["initial_prompt"] = initial_prompt

            segments, info = model.transcribe(str(wav_file), **kwargs)

            # Collect segments
            text_segments = []
            for seg in segments:
                cleaned = seg.text.strip()
                # Filter out pure whisper hallucinations on silence
                if cleaned and not cleaned.startswith("[") and not cleaned.startswith("("):
                    text_segments.append(cleaned)
                elif cleaned:
                    text_segments.append(cleaned)

            full_text = " ".join(text_segments).strip()
            inference_time = time.time() - t0

            logger.info(
                "Transcription finished in %.2fs (detected lang: %s, p=%.2f, text length: %d chars)",
                inference_time,
                info.language,
                info.language_probability,
                len(full_text),
            )

            return TranscriptionResult(
                text=full_text,
                language=info.language,
                language_probability=info.language_probability,
                duration_seconds=info.duration,
                inference_time_seconds=inference_time,
            )

        except Exception as e:
            logger.error("Transcription inference failed: %s", e)
            raise TranscriptionError(f"Transcription failed: {e}") from e
