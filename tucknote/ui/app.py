"""Main Application Coordinator connecting hotkey, audio, transcription, storage, and UI."""

from __future__ import annotations

import os
import uuid
import logging
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from tucknote.config import AppConfig, get_db_path, get_temp_audio_dir
from tucknote.context.window import WindowContextGrabber
from tucknote.audio.recorder import AudioRecorder, AudioError, NoMicrophoneError
from tucknote.transcription.transcriber import WhisperTranscriber, TranscriptionError
from tucknote.storage.models import Note, WindowContext
from tucknote.storage.repository import NoteRepository
from tucknote.hotkey.listener import GlobalHotkeyListener, HotkeyRegistrationError
from tucknote.ui.tray import ThoughtCaptureTray
from tucknote.ui.library_window import LibraryWindow

logger = logging.getLogger("tucknote")


class StateCoordinator(QObject):
    """Coordinates state transitions, background worker threads, and UI notifications."""

    # Thread-safe signals to communicate with Qt main thread
    hotkey_pressed = Signal()
    recording_started = Signal()
    recording_stopped = Signal(object, object)  # (Path, WindowContext)
    transcription_finished = Signal(object)      # Note
    transcription_failed = Signal(str, object, object)  # (error_str, wav_path, WindowContext)
    no_speech_detected = Signal()
    error_occurred = Signal(str)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.state = "ready"  # ready, recording, processing, error

        # Storage
        self.db_path = get_db_path()
        self.repository = NoteRepository(self.db_path)

        # Context Grabber
        self.context_grabber = WindowContextGrabber()

        # Audio Recorder
        self.recorder = AudioRecorder(
            sample_rate=config.sample_rate,
            channels=config.channels,
            max_duration_seconds=config.max_recording_seconds,
            on_max_duration_reached=self._on_max_duration_reached,
        )

        # Transcriber
        self.transcriber = WhisperTranscriber(
            model_size_or_path=config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
            language=config.whisper_language,
        )

        # UI Components
        self.tray = ThoughtCaptureTray(hotkey_str=config.hotkey_str)
        self.library_window = LibraryWindow(self.repository)

        # State tracking
        self._current_context: WindowContext | None = None
        self._current_wav_path: Path | None = None
        self._last_failed_wav: Path | None = None
        self._last_failed_context: WindowContext | None = None

        # Clean old temp audio leftovers from previous sessions
        self._cleanup_old_temp_recordings()

        # Connect internal Qt signals
        self._wire_signals()

        # Hotkey listener
        self.hotkey_listener = GlobalHotkeyListener(
            hotkey_str=config.hotkey_str,
            on_triggered=self._on_hotkey_thread_callback,
        )

    def _cleanup_old_temp_recordings(self) -> None:
        """Clean orphaned temp audio files from previous crashes or sessions."""
        try:
            temp_dir = get_temp_audio_dir()
            for f in temp_dir.glob("capture_*.wav"):
                try:
                    f.unlink()
                except Exception:
                    pass
        except Exception as e:
            logger.debug("Temp audio cleanup exception: %s", e)

    def _wire_signals(self) -> None:
        self.hotkey_pressed.connect(self.toggle_recording)
        self.recording_started.connect(self._handle_recording_started)
        self.recording_stopped.connect(self._handle_recording_stopped)
        self.transcription_finished.connect(self._handle_transcription_finished)
        self.transcription_failed.connect(self._handle_transcription_failed)
        self.no_speech_detected.connect(self._handle_no_speech_detected)
        self.error_occurred.connect(self._handle_error_occurred)

        # Tray signals
        self.tray.signals.open_library_requested.connect(self.open_library)
        self.tray.signals.toggle_recording_requested.connect(self.toggle_recording)
        self.tray.signals.cancel_recording_requested.connect(self.cancel_recording)
        self.tray.signals.retry_last_requested.connect(self.retry_last_failed)
        self.tray.signals.discard_last_requested.connect(self.discard_last_failed)
        self.tray.signals.quit_requested.connect(self.quit_application)

    def start(self) -> None:
        """Start the app, register hotkey, show tray icon."""
        self.tray.show()
        self.tray.update_state("ready")

        # Preload whisper model in background thread
        threading.Thread(target=self._preload_whisper, daemon=True).start()

        # Register global hotkey
        try:
            self.hotkey_listener.start()
            logger.info("Application ready. Hotkey: %s", self.config.hotkey_str)
        except HotkeyRegistrationError as e:
            logger.warning("Hotkey conflict on startup: %s", e)
            self.tray.showMessage(
                "Thought Capture — Hinweis",
                f"Globaler Hotkey {self.config.hotkey_str} ist belegt.\n"
                f"Aufnahmen können stattdessen über das Tray-Menü gestartet werden.",
                QSystemTrayIcon.Warning,
                5000,
            )
        except Exception as e:
            logger.error("Failed to start hotkey listener: %s", e)

    def _preload_whisper(self) -> None:
        try:
            self.transcriber.load_model()
        except Exception as e:
            logger.warning("Preloading whisper model failed: %s", e)

    def _on_hotkey_thread_callback(self) -> None:
        """Called directly on Win32 message loop thread when WM_HOTKEY fires."""
        # IF we are ready to start recording, capture foreground window right NOW
        # before any UI interaction!
        if self.state == "ready":
            self._current_context = self.context_grabber.capture_active_window()
        # Post event to Qt main thread
        self.hotkey_pressed.emit()

    def _on_max_duration_reached(self) -> None:
        """Watchdog callback when max recording limit is reached."""
        self.hotkey_pressed.emit()

    @Slot()
    def toggle_recording(self) -> None:
        """Main hotkey action: starts if ready, stops if recording."""
        if self.state == "ready":
            self._start_recording()
        elif self.state == "recording":
            self._stop_recording()
        elif self.state == "processing":
            logger.debug("Hotkey ignored while processing.")
        elif self.state == "error":
            # Start fresh capture on hotkey even if previous had an error
            self.discard_last_failed()
            self._start_recording()

    def _start_recording(self) -> None:
        if not self._current_context:
            self._current_context = self.context_grabber.capture_active_window()

        temp_dir = get_temp_audio_dir()
        self._current_wav_path = temp_dir / f"capture_{uuid.uuid4().hex}.wav"

        try:
            self.recorder.start()
            self.state = "recording"
            self.recording_started.emit()
        except NoMicrophoneError:
            self.state = "ready"
            self._current_context = None
            self.error_occurred.emit("Kein Mikrofon gefunden.")
        except AudioError as e:
            self.state = "ready"
            self._current_context = None
            self.error_occurred.emit(f"Audio-Fehler: {e}")

    def _stop_recording(self) -> None:
        self.state = "processing"
        self.tray.update_state("processing")

        wav_path = self._current_wav_path
        ctx = self._current_context or self.context_grabber.capture_active_window()

        self._current_wav_path = None
        self._current_context = None

        # Execute audio stop and transcription in background worker thread
        def worker():
            saved_path, duration = self.recorder.stop(wav_path)
            if not saved_path or duration < 0.3 or not saved_path.exists():
                self.no_speech_detected.emit()
                if saved_path and saved_path.exists():
                    saved_path.unlink()
                return

            try:
                res = self.transcriber.transcribe(saved_path)
                if not res.text.strip():
                    self.no_speech_detected.emit()
                    saved_path.unlink()
                    return

                note = Note(
                    id=str(uuid.uuid4()),
                    captured_at_utc=ctx.captured_at_utc,
                    transcript=res.text.strip(),
                    application=ctx.application,
                    window_title=ctx.window_title,
                )
                self.repository.save(note)
                saved_path.unlink()  # Audio deleted upon successful note save
                self.transcription_finished.emit(note)

            except Exception as exc:
                logger.error("Processing failed: %s", exc)
                self.transcription_failed.emit(str(exc), saved_path, ctx)

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def cancel_recording(self) -> None:
        """Cancel ongoing recording immediately and discard audio."""
        if self.state == "recording":
            self.recorder.cancel()
            if self._current_wav_path and self._current_wav_path.exists():
                try:
                    self._current_wav_path.unlink()
                except Exception:
                    pass
            self._current_wav_path = None
            self._current_context = None
            self.state = "ready"
            self.tray.update_state("ready")
            self.tray.showMessage("Thought Capture", "Aufnahme abgebrochen.", QSystemTrayIcon.Information, 1500)

    @Slot()
    def retry_last_failed(self) -> None:
        """Retry transcribing the last failed audio recording."""
        if not self._last_failed_wav or not self._last_failed_wav.exists():
            self.tray.showMessage("Thought Capture", "Keine gespeicherte Aufnahme zum Wiederholen vorhanden.", QSystemTrayIcon.Warning, 2000)
            self.state = "ready"
            self.tray.update_state("ready")
            return

        self.state = "processing"
        self.tray.update_state("processing")

        wav_path = self._last_failed_wav
        ctx = self._last_failed_context or WindowContext()

        def worker():
            try:
                res = self.transcriber.transcribe(wav_path)
                if not res.text.strip():
                    self.no_speech_detected.emit()
                    wav_path.unlink()
                    return

                note = Note(
                    id=str(uuid.uuid4()),
                    captured_at_utc=ctx.captured_at_utc,
                    transcript=res.text.strip(),
                    application=ctx.application,
                    window_title=ctx.window_title,
                )
                self.repository.save(note)
                wav_path.unlink()
                self._last_failed_wav = None
                self._last_failed_context = None
                self.transcription_finished.emit(note)
            except Exception as exc:
                self.transcription_failed.emit(str(exc), wav_path, ctx)

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def discard_last_failed(self) -> None:
        """Discard last failed recording audio file."""
        if self._last_failed_wav and self._last_failed_wav.exists():
            try:
                self._last_failed_wav.unlink()
            except Exception:
                pass
        self._last_failed_wav = None
        self._last_failed_context = None
        self.state = "ready"
        self.tray.update_state("ready")

    # Slot Handlers
    @Slot()
    def _handle_recording_started(self) -> None:
        self.tray.update_state("recording")
        self.tray.showMessage(
            "Thought Capture",
            f"🎙️ Recording...\nPress {self.config.hotkey_str} again to finish.",
            QSystemTrayIcon.Information,
            2000,
        )

    @Slot(object, object)
    def _handle_recording_stopped(self, wav_path: Path, ctx: WindowContext) -> None:
        self.tray.update_state("processing")

    @Slot(object)
    def _handle_transcription_finished(self, note: Note) -> None:
        self.state = "ready"
        self.tray.update_state("ready")

        # Refresh library if visible
        if self.library_window.isVisible():
            self.library_window.refresh_notes()

        preview = note.transcript
        if len(preview) > 60:
            preview = preview[:57] + "..."

        ctx_str = f" [{note.application}]" if note.application else ""
        self.tray.showMessage(
            "Thought Capture — Saved",
            f"✅{ctx_str} {preview}",
            QSystemTrayIcon.Information,
            3000,
        )

    @Slot(str, object, object)
    def _handle_transcription_failed(self, error_str: str, wav_path: Path, ctx: WindowContext) -> None:
        self.state = "error"
        self._last_failed_wav = wav_path
        self._last_failed_context = ctx
        self.tray.update_state("error", "Transcription error")
        self.tray.showMessage(
            "Thought Capture — Error",
            f"Transcription failed: {error_str}\n"
            f"Audio preserved. Click 'Retry' or 'Discard' in tray menu.",
            QSystemTrayIcon.Critical,
            6000,
        )

    @Slot()
    def _handle_no_speech_detected(self) -> None:
        self.state = "ready"
        self.tray.update_state("ready")
        self.tray.showMessage(
            "Thought Capture",
            "No speech detected. Recording discarded.",
            QSystemTrayIcon.Warning,
            2500,
        )

    @Slot(str)
    def _handle_error_occurred(self, message: str) -> None:
        self.state = "ready"
        self.tray.update_state("ready")
        self.tray.showMessage(
            "Thought Capture — Notice",
            message,
            QSystemTrayIcon.Warning,
            4000,
        )

    @Slot()
    def open_library(self) -> None:
        """Show and bring Library Window to foreground."""
        self.library_window.refresh_notes()
        self.library_window.show()
        self.library_window.raise_()
        self.library_window.activateWindow()

    @Slot()
    def quit_application(self) -> None:
        """Clean shutdown of hotkey, recorder, and app."""
        logger.info("Quitting application...")
        if self.state == "recording":
            self.recorder.cancel()
        self.hotkey_listener.stop()
        self._cleanup_old_temp_recordings()
        QApplication.quit()
