"""Streaming audio transcription coordinator for live speech processing."""

from __future__ import annotations

import time
import logging
import threading
from typing import Callable
import numpy as np

from tucknote.audio.recorder import AudioRecorder
from tucknote.transcription.transcriber import WhisperTranscriber, find_audio_split_point

logger = logging.getLogger("tucknote")


def join_transcription_segments(segments: list[str]) -> str:
    """Join transcribed speech segments seamlessly, removing accidental boundary word duplicates."""
    cleaned = [s.strip() for s in segments if s and s.strip()]
    if not cleaned:
        return ""
    result = cleaned[0]
    for seg in cleaned[1:]:
        prev_words = result.split()
        curr_words = seg.split()
        if prev_words and curr_words:
            # Drop repeated boundary word if Whisper picked it up from initial_prompt context
            if prev_words[-1].lower().strip(".,!?:;") == curr_words[0].lower().strip(".,!?:;"):
                curr_words = curr_words[1:]
        if curr_words:
            result = result + " " + " ".join(curr_words)
    return result.strip()


class StreamingTranscriptionSession:
    """Coordinates background chunked speech transcription while recording is active."""

    def __init__(
        self,
        recorder: AudioRecorder,
        transcriber: WhisperTranscriber,
        initial_prompt: str | None = None,
        language: str | None = None,
        sample_rate: int = 16000,
        on_chunk_transcribed: Callable[[str, str], None] | None = None,
    ):
        self.recorder = recorder
        self.transcriber = transcriber
        self.initial_prompt = initial_prompt
        self.language = language
        self.sample_rate = sample_rate
        self.on_chunk_transcribed = on_chunk_transcribed

        self._buffer: np.ndarray = np.array([], dtype=np.int16)
        self._segments: list[str] = []
        self._processed_samples: int = 0
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the background streaming worker thread."""
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="streaming-transcriber")
        self._thread.start()
        logger.info("Streaming transcription session started.")

    def _build_prompt_with_history(self) -> str | None:
        with self._lock:
            if not self._segments:
                return self.initial_prompt
            # Include recent speech context for seamless sentence continuation
            recent_context = " ".join(self._segments[-3:])
            if len(recent_context) > 250:
                recent_context = recent_context[-250:]

        if self.initial_prompt:
            return f"{self.initial_prompt} {recent_context}"
        return recent_context

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                # 1. Pull new frames from recorder
                new_frames = self.recorder.get_unprocessed_frames()
                if len(new_frames) > 0:
                    with self._lock:
                        if len(self._buffer) > 0:
                            self._buffer = np.concatenate([self._buffer, new_frames])
                        else:
                            self._buffer = new_frames

                # 2. Check for natural phrase boundary or max chunk length
                with self._lock:
                    current_buf = self._buffer.copy()

                split_pt = find_audio_split_point(current_buf, sample_rate=self.sample_rate)

                if split_pt is not None:
                    chunk = current_buf[:split_pt]
                    with self._lock:
                        self._buffer = self._buffer[split_pt:]

                    # 3. Transcribe audio chunk in background
                    prompt = self._build_prompt_with_history()
                    res = self.transcriber.transcribe_samples(
                        chunk,
                        initial_prompt=prompt,
                        language=self.language,
                    )
                    cleaned = res.text.strip()
                    with self._lock:
                        self._processed_samples += len(chunk)
                        if cleaned:
                            self._segments.append(cleaned)
                            full_so_far = join_transcription_segments(self._segments)
                        else:
                            full_so_far = join_transcription_segments(self._segments)

                    if cleaned and self.on_chunk_transcribed:
                        try:
                            self.on_chunk_transcribed(cleaned, full_so_far)
                        except Exception as cb_err:
                            logger.warning("Error in on_chunk_transcribed callback: %s", cb_err)

            except Exception as e:
                logger.warning("Streaming worker iteration encountered error: %s", e)

            self._stop_event.wait(0.12)

    def finish(self, full_audio: np.ndarray | None = None) -> str:
        """Stop background worker, transcribe any remaining audio tail, and return complete transcript.
        
        If full_audio (from recorder.stop) is provided, exactly transcribes the remaining untranscribed
        samples (full_audio[processed_samples:]), guaranteeing ZERO missed words at the end of recording.
        """
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        # Determine untranscribed tail
        tail: np.ndarray = np.array([], dtype=np.int16)
        if full_audio is not None and len(full_audio) > 0:
            with self._lock:
                processed = self._processed_samples
            if processed < len(full_audio):
                tail = full_audio[processed:]
        else:
            # Fallback to buffer if full_audio not supplied
            try:
                final_frames = self.recorder.get_unprocessed_frames()
                if len(final_frames) > 0:
                    with self._lock:
                        if len(self._buffer) > 0:
                            self._buffer = np.concatenate([self._buffer, final_frames])
                        else:
                            self._buffer = final_frames
            except Exception as e:
                logger.debug("Error collecting final frames: %s", e)
            with self._lock:
                tail = self._buffer
                self._buffer = np.array([], dtype=np.int16)

        # Transcribe remaining tail if long enough (>= 0.15s)
        if len(tail) >= int(0.15 * self.sample_rate):
            try:
                prompt = self._build_prompt_with_history()
                res = self.transcriber.transcribe_samples(
                    tail,
                    initial_prompt=prompt,
                    language=self.language,
                )
                if res.text.strip():
                    with self._lock:
                        self._segments.append(res.text.strip())
            except Exception as e:
                logger.error("Failed transcribing final streaming tail: %s", e)

        with self._lock:
            full_text = join_transcription_segments(self._segments)
            seg_count = len(self._segments)

        logger.info(
            "Streaming session finished (%d segments, total length: %d chars).",
            seg_count,
            len(full_text),
        )
        return full_text

    def cancel(self) -> None:
        """Cancel streaming session and discard all audio and text segments."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.5)
        with self._lock:
            self._buffer = np.array([], dtype=np.int16)
            self._segments.clear()
            self._processed_samples = 0
        logger.info("Streaming transcription session canceled.")
