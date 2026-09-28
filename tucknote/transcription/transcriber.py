"""Local speech-to-text transcription engine using faster-whisper."""

from __future__ import annotations

import os
import time
import shutil
import logging
import threading
from pathlib import Path
from dataclasses import dataclass
import numpy as np

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
            "Tucknote voice note with technical terms: "
            "Antigravity, recording, clipboard, save, check, feature, issue, branch, "
            "commit, repository, pull request, frontend, backend, UI, bug, API, VS Code, Git."
        )
    else:
        # German or Auto / Denglisch
        parts.append(
            "Tucknote Sprachnotiz auf Deutsch mit Fachbegriffen und Denglisch: "
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
        on_loading_started: Callable[[str], None] | None = None,
        on_loading_finished: Callable[[str, bool, str | None], None] | None = None,
    ):
        self.model_size_or_path = model_size_or_path
        self.device = device
        self.compute_type = compute_type
        self.language = None if language == "auto" else language
        self.on_loading_started = on_loading_started
        self.on_loading_finished = on_loading_finished

        self._model = None
        self._lock = threading.Lock()
        self.is_loading = False
        self.loading_model_name: str | None = None

    def update_config(self, model_size_or_path: str | None = None, language: str | None = None) -> None:
        """Update model size or language dynamically with zero-downtime hot-reloading."""
        target_model = None
        with self._lock:
            if model_size_or_path and model_size_or_path != self.model_size_or_path:
                target_model = model_size_or_path
                self.is_loading = True
                self.loading_model_name = target_model
            if language is not None:
                self.language = None if language == "auto" else language

        if target_model:
            if self.on_loading_started:
                try:
                    self.on_loading_started(target_model)
                except Exception:
                    pass

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
                        self.is_loading = False
                        self.loading_model_name = None
                    logger.info("Whisper model '%s' is now loaded and active.", target_model)
                    if self.on_loading_finished:
                        self.on_loading_finished(target_model, True, None)
                except Exception as e:
                    with self._lock:
                        self.is_loading = False
                        self.loading_model_name = None
                    logger.error("Failed to load model '%s': %s", target_model, e)
                    if self.on_loading_finished:
                        self.on_loading_finished(target_model, False, str(e))

            threading.Thread(target=_bg_worker, daemon=True, name="whisper-loader").start()

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

    def _run_inference(
        self,
        audio: str | np.ndarray,
        initial_prompt: str | None = None,
        language: str | None = None,
    ) -> TranscriptionResult:
        model = self._ensure_model_loaded()
        t0 = time.time()

        try:
            effective_lang = self.language if language is None else (None if language == "auto" else language)

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

            segments, info = model.transcribe(audio, **kwargs)

            text_segments = []
            for seg in segments:
                cleaned = seg.text.strip()
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

        logger.info("Transcribing audio file (%d bytes)...", file_size)
        return self._run_inference(str(wav_file), initial_prompt=initial_prompt, language=language)

    def transcribe_samples(
        self,
        samples: np.ndarray,
        initial_prompt: str | None = None,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Transcribe in-memory 16kHz audio samples directly without disk I/O.
        
        samples: 1D np.ndarray of int16 or float32.
        """
        if len(samples) == 0:
            return TranscriptionResult(text="")

        if samples.dtype == np.int16:
            audio = (samples.astype(np.float32) / 32768.0).flatten()
        elif samples.dtype != np.float32:
            audio = samples.astype(np.float32).flatten()
        else:
            audio = samples.flatten()

        duration = len(audio) / 16000.0
        if duration < 0.2:
            return TranscriptionResult(text="", duration_seconds=duration)

        logger.info("Transcribing audio samples (%.2fs)...", duration)
        return self._run_inference(audio, initial_prompt=initial_prompt, language=language)


def find_audio_split_point(
    buffer: np.ndarray,
    sample_rate: int = 16000,
    min_seconds: float = 2.5,
    max_seconds: float = 4.5,
    silence_threshold: int = 400,
    silence_window_sec: float = 0.35,
) -> int | None:
    """Find optimal split point in 16-bit PCM audio buffer based on silence pauses or valleys.
    
    Returns the sample index where to split, or None if buffer should keep accumulating.
    """
    min_samples = int(min_seconds * sample_rate)
    max_samples = int(max_seconds * sample_rate)
    if len(buffer) < min_samples:
        return None

    silence_window = int(silence_window_sec * sample_rate)
    tail = buffer[-silence_window:]
    if np.max(np.abs(tail)) < silence_threshold:
        return len(buffer)

    if len(buffer) >= max_samples:
        search_start = min_samples
        search_end = max_samples
        valley_len = int(0.10 * sample_rate)  # 100ms valley
        best_point = search_end
        lowest_energy = float("inf")
        step = int(0.05 * sample_rate)  # 50ms step
        for pt in range(search_start, search_end - valley_len, step):
            segment = buffer[pt : pt + valley_len]
            energy = float(np.mean(np.abs(segment.astype(np.float32))))
            if energy < lowest_energy:
                lowest_energy = energy
                best_point = pt + valley_len // 2
        return best_point

    return None


def get_whisper_model_dir(model_name: str) -> Path | None:
    """Get the cached directory on disk for a given faster-whisper model."""
    try:
        import os
        from huggingface_hub.constants import HUGGINGFACE_HUB_CACHE
        cache_env = os.environ.get("HF_HUB_CACHE") or os.environ.get("HF_HOME")
        cache_dir = Path(cache_env) if cache_env else Path(HUGGINGFACE_HUB_CACHE)
        if not cache_dir.exists():
            return None
        patterns = [
            f"models--Systran--faster-whisper-{model_name}",
            f"models--mobiuslabsgmbh--faster-whisper-{model_name}",
            f"models--*{model_name}*",
        ]
        for pattern in patterns:
            for p in cache_dir.glob(pattern):
                if p.is_dir():
                    return p
    except Exception as e:
        logger.debug("Error finding model directory for '%s': %s", model_name, e)
    return None


def is_whisper_model_cached(model_name: str) -> bool:
    """Check if a faster-whisper model is already downloaded and cached locally on this PC."""
    model_dir = get_whisper_model_dir(model_name)
    if model_dir and model_dir.exists():
        if any(model_dir.rglob("*.bin")) or any(model_dir.rglob("*.safetensors")) or any(model_dir.rglob("*.json")):
            return True
    try:
        from faster_whisper import download_model
        download_model(model_name, local_files_only=True)
        return True
    except Exception:
        return False


def get_whisper_model_size_mb(model_name: str) -> float:
    """Return disk space consumed by cached model in megabytes, or 0.0 if not cached."""
    model_dir = get_whisper_model_dir(model_name)
    if not model_dir or not model_dir.exists():
        return 0.0
    try:
        total_bytes = sum(f.stat().st_size for f in model_dir.rglob("*") if f.is_file())
        return round(total_bytes / (1024 * 1024), 1)
    except Exception:
        return 0.0



def delete_whisper_model(model_name: str) -> bool:
    """Permanently delete a downloaded faster-whisper model from the local HuggingFace cache."""
    model_dir = get_whisper_model_dir(model_name)
    if not model_dir or not model_dir.exists():
        return False
    try:
        logger.info("Deleting cached Whisper model '%s' at %s...", model_name, model_dir)
        shutil.rmtree(str(model_dir), ignore_errors=False)
        return True
    except Exception as e:
        logger.error("Failed to delete Whisper model '%s': %s", model_name, e)
        return False
