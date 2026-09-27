"""Audio recorder module using sounddevice to capture microphone audio into 16kHz WAV."""

from __future__ import annotations

import io
import wave
import time
import logging
import threading
from pathlib import Path
from typing import Callable
import numpy as np

logger = logging.getLogger("tucknote")


class AudioError(Exception):
    """Base exception for audio recording errors."""
    pass


class NoMicrophoneError(AudioError):
    """Raised when no input audio device is available."""
    pass


def normalize_audio_frames(
    raw_data: np.ndarray,
    target_headroom: float = 0.95,
    max_gain: float = 8.0,
    min_peak_threshold: int = 150,
) -> np.ndarray:
    """Peak-normalizes 16-bit PCM audio frames to optimal volume level for Whisper.
    
    Prevents Whisper phonetic hallucinations on quiet sentence starts while
    avoiding amplifying pure background noise floor.
    """
    if len(raw_data) == 0:
        return raw_data

    peak = int(np.max(np.abs(raw_data)))
    if peak < min_peak_threshold:
        return raw_data

    target_peak = 32767.0 * target_headroom
    gain = min(target_peak / peak, max_gain)

    if gain <= 1.05:
        return raw_data

    logger.debug("Normalizing audio: peak %d -> target %.0f (gain: %.2fx)", peak, target_peak, gain)
    normalized = np.clip(raw_data.astype(np.float32) * gain, -32768, 32767).astype(np.int16)
    return normalized


class AudioRecorder:
    """Manages recording from default input audio device to WAV."""

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        max_duration_seconds: int = 120,
        on_max_duration_reached: Callable[[], None] | None = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_duration_seconds = max_duration_seconds
        self.on_max_duration_reached = on_max_duration_reached

        self._lock = threading.Lock()
        self._stream = None
        self._frames: list[np.ndarray] = []
        self._is_recording = False
        self._start_time: float = 0.0
        self._max_timer: threading.Timer | None = None

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._is_recording

    @property
    def elapsed_seconds(self) -> float:
        with self._lock:
            if not self._is_recording:
                return 0.0
            return time.time() - self._start_time

    def start(self) -> None:
        """Start recording from the default input device."""
        import sounddevice as sd

        with self._lock:
            if self._is_recording:
                logger.warning("Recorder already running, ignoring start request.")
                return

            # Check for input devices
            try:
                devices = sd.query_devices()
                default_input = sd.default.device[0]
                if default_input is None or default_input < 0:
                    # Search for any device with input channels > 0
                    has_input = any(d.get("max_input_channels", 0) > 0 for d in devices)
                    if not has_input:
                        raise NoMicrophoneError("No microphone or audio input device found.")
            except Exception as e:
                if isinstance(e, NoMicrophoneError):
                    raise
                logger.error("Failed querying audio devices: %s", e)
                raise AudioError(f"Audio device query failed: {e}") from e

            self._frames = []
            self._start_time = time.time()

            try:
                self._stream = sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="int16",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._is_recording = True
            except Exception as e:
                self._stream = None
                self._is_recording = False
                logger.error("Failed starting audio stream: %s", e)
                raise AudioError(f"Could not open microphone stream: {e}") from e

            # Start watchdog timer for max duration
            if self.max_duration_seconds > 0:
                self._max_timer = threading.Timer(
                    self.max_duration_seconds, self._on_timer_expire
                )
                self._max_timer.daemon = True
                self._max_timer.start()

        logger.info("Audio recording started.")

    def _audio_callback(self, indata: np.ndarray, frames_count: int, time_info, status) -> None:
        if status:
            logger.debug("Audio stream status flag: %s", status)
        with self._lock:
            if self._is_recording:
                self._frames.append(indata.copy())

    def _on_timer_expire(self) -> None:
        logger.info("Max recording duration reached (%ss).", self.max_duration_seconds)
        if self.on_max_duration_reached:
            try:
                self.on_max_duration_reached()
            except Exception as e:
                logger.error("Error in on_max_duration_reached callback: %s", e)

    def stop(self, target_wav_path: Path | str | None = None) -> tuple[Path | None, float]:
        """Stop recording and save captured frames to target_wav_path.
        
        Returns (saved_file_path, duration_seconds).
        If no audio was captured, returns (None, 0.0).
        """
        with self._lock:
            if not self._is_recording:
                logger.debug("Recorder not running when stop was requested.")
                return None, 0.0

            self._is_recording = False

            if self._max_timer:
                self._max_timer.cancel()
                self._max_timer = None

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    logger.debug("Error stopping audio stream: %s", e)
                self._stream = None

            frames_copy = self._frames
            self._frames = []

        if not frames_copy:
            logger.info("No audio frames recorded (duration was 0).")
            return None, 0.0

        raw_data = np.concatenate(frames_copy, axis=0)
        raw_data = normalize_audio_frames(raw_data)
        num_samples = len(raw_data)
        duration_seconds = num_samples / self.sample_rate

        if num_samples == 0:
            return None, 0.0

        if target_wav_path is None:
            # Caller didn't provide path
            return None, duration_seconds

        target_path = Path(target_wav_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        with wave.open(str(target_path), "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(2)  # 16-bit
            wf.setframerate(self.sample_rate)
            wf.writeframes(raw_data.tobytes())

        logger.info(
            "Audio recording saved: %s (%.2f seconds)",
            target_path.name,
            duration_seconds,
        )
        return target_path, duration_seconds

    def cancel(self) -> None:
        """Cancel the current recording and discard all captured audio."""
        with self._lock:
            self._is_recording = False
            if self._max_timer:
                self._max_timer.cancel()
                self._max_timer = None

            if self._stream:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as e:
                    logger.debug("Error canceling audio stream: %s", e)
                self._stream = None

            self._frames = []
        logger.info("Audio recording canceled and discarded.")
