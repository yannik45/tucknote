"""Main Application Coordinator connecting hotkey, audio, transcription, storage, and UI."""

from __future__ import annotations

import os
import uuid
import logging
import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from tucknote.config import AppConfig, AppSettings, get_db_path, get_temp_audio_dir
from tucknote.context.window import WindowContextGrabber
from tucknote.audio.recorder import AudioRecorder, AudioError, NoMicrophoneError
from tucknote.transcription.transcriber import WhisperTranscriber, TranscriptionError, build_default_prompt
from tucknote.transcription.streaming import StreamingTranscriptionSession
from tucknote.transcription.processor import get_default_text_processor, RuleBasedTextProcessor
from tucknote.storage.models import Note, WindowContext
from tucknote.storage.repository import NoteRepository
from tucknote.hotkey.listener import GlobalHotkeyListener, HotkeyRegistrationError
from tucknote.ui.tray import ThoughtCaptureTray
from tucknote.ui.library_window import LibraryWindow
from tucknote.ui.overlay import RecordingOverlay

logger = logging.getLogger("tucknote")


class StateCoordinator(QObject):
    """Coordinates state transitions, background worker threads, and UI notifications."""

    # Thread-safe signals to communicate with Qt main thread
    hotkey_pressed = Signal()
    recording_started = Signal()
    recording_stopped = Signal(object, object)  # (Path, WindowContext)
    transcription_finished = Signal(object)      # Note
    transcription_failed = Signal(str, object, object)  # (error_str, wav_path, WindowContext)
    note_refined = Signal(object)                # Note (asynchronously refined by LLM)
    no_speech_detected = Signal()
    error_occurred = Signal(str)
    model_loading_started = Signal(str)          # model_name
    model_loading_finished = Signal(str, bool, str)  # (model_name, success, error_msg)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.settings = config.settings
        self.state = "ready"  # ready, recording, processing, error

        # Storage
        self.db_path = get_db_path()
        self.repository = NoteRepository(self.db_path)

        # Context Grabber
        self.context_grabber = WindowContextGrabber()

        # Text processor
        self.text_processor = get_default_text_processor(
            engine=self.settings.refinement_engine,
            model_key=self.settings.llm_model,
        )

        # Audio Recorder
        self.recorder = AudioRecorder(
            sample_rate=config.sample_rate,
            channels=config.channels,
            max_duration_seconds=config.max_recording_seconds,
            on_max_duration_reached=self._on_max_duration_reached,
        )

        # Transcriber
        self.transcriber = WhisperTranscriber(
            model_size_or_path=self.settings.whisper_model or config.whisper_model,
            device=config.whisper_device,
            compute_type=config.whisper_compute_type,
            language=self.settings.whisper_language or config.whisper_language,
            on_loading_started=lambda m: self.model_loading_started.emit(m),
            on_loading_finished=lambda m, s, err: self.model_loading_finished.emit(m, s, err or ""),
        )

        # UI Components
        self.tray = ThoughtCaptureTray(hotkey_str=config.hotkey_str)
        self.library_window = LibraryWindow(self.repository, settings=self.settings)
        self.library_window.set_text_processor(self.text_processor)
        self.overlay = RecordingOverlay(self.settings)

        # State tracking
        self._current_context: WindowContext | None = None
        self._current_wav_path: Path | None = None
        self._attached_screenshot: Path | None = None
        self._last_failed_wav: Path | None = None
        self._last_failed_context: WindowContext | None = None
        self._streaming_session: StreamingTranscriptionSession | None = None

        # Clean old temp audio leftovers from previous sessions
        self._cleanup_old_temp_recordings()

        # Connect internal Qt signals
        self._wire_signals()

        # Hotkey listener
        self.hotkey_listener = GlobalHotkeyListener(
            hotkey_str=config.hotkey_str,
            on_triggered=self._on_hotkey_thread_callback,
        )

        # Periodic background poll to keep external foreground context fresh
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(200)
        self._poll_timer.timeout.connect(self.context_grabber.poll_external_window)

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
        self.note_refined.connect(self._handle_note_refined)
        self.no_speech_detected.connect(self._handle_no_speech_detected)
        self.error_occurred.connect(self._handle_error_occurred)
        self.model_loading_started.connect(self._on_model_loading_started)
        self.model_loading_finished.connect(self._on_model_loading_finished)

        # Tray signals
        self.tray.signals.open_library_requested.connect(self.open_library)
        self.tray.signals.open_settings_requested.connect(self.open_settings)
        self.tray.signals.toggle_overlay_requested.connect(self.toggle_overlay)
        self.tray.signals.toggle_recording_requested.connect(self.toggle_recording)
        self.tray.signals.cancel_recording_requested.connect(self.cancel_recording)
        self.tray.signals.retry_last_requested.connect(self.retry_last_failed)
        self.tray.signals.discard_last_requested.connect(self.discard_last_failed)
        self.tray.signals.quit_requested.connect(self.quit_application)

        # Overlay signals
        self.overlay.toggle_recording_requested.connect(self.toggle_recording)
        self.overlay.cancel_recording_requested.connect(self.cancel_recording)
        self.overlay.open_library_requested.connect(self.open_library)
        self.overlay.screenshot_attached.connect(self._on_screenshot_attached)
        self.overlay.copy_text_requested.connect(self._on_overlay_copied)
        self.overlay.hide_requested.connect(lambda: self.set_overlay_visibility(False))

        # Library signals
        self.library_window.overlay_visibility_toggled.connect(self.set_overlay_visibility)
        self.library_window.notifications_enabled_toggled.connect(self.set_notifications_enabled)
        self.library_window.whisper_model_changed.connect(self._on_model_changed)
        self.library_window.whisper_language_changed.connect(self._on_language_changed)
        self.library_window.refinement_engine_changed.connect(self._on_refinement_engine_changed)
        self.library_window.llm_model_changed.connect(self._on_llm_model_changed)
        self.library_window.streaming_transcription_toggled.connect(self._on_streaming_transcription_toggled)

    def start(self) -> None:
        """Start the app, register hotkey, show tray icon and overlay."""
        self.tray.show()
        self.tray.update_state("ready")
        self.tray.set_overlay_visible(self.settings.overlay_visible)

        if self.settings.overlay_visible:
            self.overlay.show()

        # Start external window poll timer
        self._poll_timer.start()

        # Preload whisper model and local LLM server in background
        threading.Thread(target=self._preload_whisper, daemon=True).start()
        if hasattr(self.text_processor, "start_server_async"):
            self.text_processor.start_server_async()

        # Register global hotkey
        try:
            self.hotkey_listener.start()
            logger.info("Application ready. Hotkey: %s", self.config.hotkey_str)
        except HotkeyRegistrationError as e:
            logger.warning("Hotkey conflict on startup: %s", e)
            self._show_tray_message(
                "Tucknote — Notice",
                f"Global hotkey {self.config.hotkey_str} is already in use.\n"
                f"You can use the floating overlay or tray menu instead.",
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

    def _show_tray_message(
        self,
        title: str,
        message: str,
        icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.Information,
        msecs: int = 3000,
    ) -> None:
        """Show system notification popup if enabled in settings."""
        if self.settings.show_notifications:
            self.tray.showMessage(title, message, icon, msecs)

    def _on_hotkey_thread_callback(self) -> None:
        """Called directly on Win32 message loop thread when WM_HOTKEY fires."""
        if self.state == "ready":
            self._current_context = self.context_grabber.capture_active_window(allow_self=False)
        self.hotkey_pressed.emit()

    def _on_max_duration_reached(self) -> None:
        """Watchdog callback when max recording limit is reached."""
        self.hotkey_pressed.emit()

    @Slot(object)
    def _on_screenshot_attached(self, path: Path | None) -> None:
        self._attached_screenshot = path
        logger.info("Screenshot attachment updated: %s", path)

    @Slot(str)
    def _on_overlay_copied(self, text: str) -> None:
        self._show_tray_message("Tucknote", "Text copied to clipboard.", QSystemTrayIcon.Information, 1500)

    @Slot()
    def toggle_overlay(self) -> None:
        """Toggle floating overlay visibility from tray menu."""
        new_visible = not self.overlay.isVisible()
        self.set_overlay_visibility(new_visible)

    @Slot(bool)
    def set_overlay_visibility(self, visible: bool) -> None:
        """Set overlay visibility and persist preference."""
        self.overlay.setVisible(visible)
        self.tray.set_overlay_visible(visible)
        self.settings.overlay_visible = visible
        self.settings.save()
        self.library_window.update_overlay_checkbox(visible)

    @Slot(bool)
    def set_notifications_enabled(self, enabled: bool) -> None:
        """Set Windows notification popups preference and persist."""
        self.settings.show_notifications = enabled
        self.settings.save()
        self.library_window.update_notifications_checkbox(enabled)

    @Slot()
    def open_settings(self) -> None:
        """Open Library window and expand settings panel."""
        self.open_library()
        self.library_window.open_settings()

    @Slot(str)
    def _on_model_changed(self, model: str) -> None:
        self.settings.whisper_model = model
        self.settings.save()
        self.transcriber.update_config(model_size_or_path=model)

    @Slot(str)
    def _on_model_loading_started(self, model: str) -> None:
        self.library_window.show_model_loading(model)
        self._show_tray_message("Tucknote", f"Modell '{model}' wird geladen...", QSystemTrayIcon.Information, 2500)

    @Slot(str, bool, str)
    def _on_model_loading_finished(self, model: str, success: bool, err_msg: str) -> None:
        self.library_window.hide_model_loading(model, success=success, error_message=err_msg)
        if success:
            self._show_tray_message("Tucknote", f"Modell '{model}' geladen & einsatzbereit.", QSystemTrayIcon.Information, 2500)
        else:
            self._show_tray_message("Tucknote", f"Fehler beim Laden von '{model}': {err_msg}", QSystemTrayIcon.Warning, 4000)

    @Slot(str)
    def _on_language_changed(self, lang: str) -> None:
        self.settings.whisper_language = lang
        self.settings.save()
        self.transcriber.update_config(language=lang)
        self._show_tray_message("Tucknote", f"Sprache auf '{lang}' gesetzt.", QSystemTrayIcon.Information, 2000)

    @Slot(str)
    def _on_refinement_engine_changed(self, engine: str) -> None:
        self.settings.refinement_engine = engine
        self.settings.save()
        try:
            self.text_processor.stop()
        except Exception:
            pass
        self.text_processor = get_default_text_processor(
            engine=engine,
            model_key=self.settings.llm_model,
        )
        self.library_window.set_text_processor(self.text_processor)
        self._show_tray_message("Tucknote", f"Textverarbeitung: '{engine}'", QSystemTrayIcon.Information, 2000)

    @Slot(str)
    def _on_llm_model_changed(self, model: str) -> None:
        self.settings.llm_model = model
        self.settings.save()
        if hasattr(self.text_processor, "update_model"):
            self.text_processor.update_model(model)
        else:
            self.text_processor = get_default_text_processor(
                engine=self.settings.refinement_engine,
                model_key=model,
            )
            self.library_window.set_text_processor(self.text_processor)
        self._show_tray_message("Tucknote", f"LLM-Modell: '{model}'", QSystemTrayIcon.Information, 2000)

    @Slot(bool)
    def _on_streaming_transcription_toggled(self, enabled: bool) -> None:
        self.settings.streaming_transcription = enabled
        self.settings.save()
        msg = "Live-Streaming aktiv (minimale Latenz nach Stopp)." if enabled else "Standard-Batch-Transkription aktiv."
        self._show_tray_message("Tucknote", msg, QSystemTrayIcon.Information, 2000)

    @Slot()
    def toggle_recording(self) -> None:
        """Main action: starts if ready, stops if recording (unified for button & hotkey)."""
        if self.state == "ready":
            self._start_recording()
        elif self.state == "recording":
            self._stop_recording()
        elif self.state == "processing":
            logger.debug("Action ignored while processing.")
        elif self.state == "error":
            self.discard_last_failed()
            self._start_recording()

    def _start_recording(self) -> None:
        # If context not yet captured (e.g. triggered via overlay button click), grab now
        if not self._current_context:
            self._current_context = self.context_grabber.capture_active_window(allow_self=False)

        temp_dir = get_temp_audio_dir()
        self._current_wav_path = temp_dir / f"capture_{uuid.uuid4().hex}.wav"

        try:
            self.recorder.start()
            self.state = "recording"
            self.recording_started.emit()

            if self.settings.streaming_transcription:
                prompt = build_default_prompt(
                    application=self._current_context.application if self._current_context else None,
                    window_title=self._current_context.window_title if self._current_context else None,
                    language=self.settings.whisper_language,
                )
                self._streaming_session = StreamingTranscriptionSession(
                    recorder=self.recorder,
                    transcriber=self.transcriber,
                    initial_prompt=prompt,
                    language=self.settings.whisper_language,
                    sample_rate=self.config.sample_rate,
                )
                self._streaming_session.start()
        except NoMicrophoneError:
            self.state = "ready"
            self._current_context = None
            self.error_occurred.emit("No microphone or audio input device found.")
        except AudioError as e:
            self.state = "ready"
            self._current_context = None
            self.error_occurred.emit(f"Audio error: {e}")

    def _stop_recording(self) -> None:
        self.state = "processing"
        self.tray.update_state("processing")
        self.overlay.update_state("processing")

        wav_path = self._current_wav_path
        ctx = self._current_context or self.context_grabber.capture_active_window(allow_self=False)
        screenshot_path = str(self._attached_screenshot) if self._attached_screenshot and self._attached_screenshot.exists() else None
        streaming_session = self._streaming_session
        self._streaming_session = None

        self._current_wav_path = None
        self._current_context = None
        self._attached_screenshot = None

        def worker():
            saved_path, duration = self.recorder.stop(wav_path)
            if not saved_path or duration < 0.3 or not saved_path.exists():
                if streaming_session:
                    streaming_session.cancel()
                self.no_speech_detected.emit()
                if saved_path and saved_path.exists():
                    saved_path.unlink()
                if screenshot_path and Path(screenshot_path).exists():
                    try:
                        Path(screenshot_path).unlink()
                    except Exception:
                        pass
                return

            try:
                raw_text = ""
                if streaming_session:
                    try:
                        raw_text = streaming_session.finish(full_audio=self.recorder.last_raw_audio)
                    except Exception as s_err:
                        logger.warning("Streaming session failed to finish, falling back to batch: %s", s_err)

                # If streaming was disabled or returned empty text, fall back to batch transcription
                if not raw_text:
                    prompt = build_default_prompt(
                        application=ctx.application,
                        window_title=ctx.window_title,
                        language=self.settings.whisper_language,
                    )
                    res = self.transcriber.transcribe(
                        saved_path,
                        initial_prompt=prompt,
                        language=self.settings.whisper_language,
                    )
                    raw_text = res.text.strip()

                if not raw_text:
                    self.no_speech_detected.emit()
                    saved_path.unlink()
                    if screenshot_path and Path(screenshot_path).exists():
                        try:
                            Path(screenshot_path).unlink()
                        except Exception:
                            pass
                    return

                # Instant Rule-Based Normalization (<1ms)
                rule_proc = RuleBasedTextProcessor()
                fast_proc_res = rule_proc.process(
                    raw_text,
                    context_app=ctx.application,
                    context_window=ctx.window_title,
                    language=self.settings.whisper_language,
                )
                fast_text_processed = (
                    fast_proc_res.text if (fast_proc_res.success and fast_proc_res.text != raw_text) else None
                )
                fast_category = fast_proc_res.category if fast_proc_res.success else None
                fast_tags = fast_proc_res.tags if fast_proc_res.success else []

                note = Note(
                    id=str(uuid.uuid4()),
                    captured_at_utc=ctx.captured_at_utc,
                    transcript=raw_text,
                    original_transcript=raw_text,
                    text_processed=fast_text_processed,
                    processed_by="rules" if fast_text_processed else None,
                    category=fast_category,
                    tags=fast_tags,
                    screenshot_path=screenshot_path,
                    application=ctx.application,
                    window_title=ctx.window_title,
                )
                self.repository.save(note)
                saved_path.unlink()  # Audio deleted upon successful note save

                # Instant UI emit (<1s response for user)
                self.transcription_finished.emit(note)

                # Async LLM Refinement & Categorization in background (non-blocking)
                if self.settings.refinement_engine == "llm":
                    note_id = note.id
                    app_name = ctx.application
                    win_title = ctx.window_title
                    lang = self.settings.whisper_language

                    def bg_llm_worker():
                        try:
                            llm_res = self.text_processor.process(
                                raw_text,
                                context_app=app_name,
                                context_window=win_title,
                                language=lang,
                            )
                            if llm_res.success:
                                refined_text = llm_res.text if llm_res.text != raw_text else None
                                updated = self.repository.update_processed_text(
                                    note_id,
                                    text_processed=refined_text or (fast_text_processed or ""),
                                    processed_by=llm_res.processor_id,
                                    category=llm_res.category or fast_category,
                                    tags=llm_res.tags or fast_tags,
                                )
                                if updated:
                                    self.note_refined.emit(updated)
                        except Exception as e:
                            logger.warning("Background LLM processing failed: %s", e)

                    threading.Thread(target=bg_llm_worker, daemon=True).start()

            except Exception as exc:
                logger.error("Processing failed: %s", exc)
                self.transcription_failed.emit(str(exc), saved_path, ctx)

        threading.Thread(target=worker, daemon=True).start()

    @Slot()
    def cancel_recording(self) -> None:
        """Cancel ongoing recording immediately and discard audio & screenshot."""
        if self.state == "recording":
            if self._streaming_session:
                self._streaming_session.cancel()
                self._streaming_session = None
            self.recorder.cancel()
            if self._current_wav_path and self._current_wav_path.exists():
                try:
                    self._current_wav_path.unlink()
                except Exception:
                    pass
            if self._attached_screenshot and self._attached_screenshot.exists():
                try:
                    self._attached_screenshot.unlink()
                except Exception:
                    pass

            self._current_wav_path = None
            self._current_context = None
            self._attached_screenshot = None
            self.state = "ready"
            self.tray.update_state("ready")
            self.overlay.update_state("ready")
            self._show_tray_message("Tucknote", "Recording canceled.", QSystemTrayIcon.Information, 1500)

    @Slot()
    def retry_last_failed(self) -> None:
        """Retry transcribing the last failed audio recording."""
        if not self._last_failed_wav or not self._last_failed_wav.exists():
            self._show_tray_message("Tucknote", "No saved recording to retry.", QSystemTrayIcon.Warning, 2000)
            self.state = "ready"
            self.tray.update_state("ready")
            self.overlay.update_state("ready")
            return

        self.state = "processing"
        self.tray.update_state("processing")
        self.overlay.update_state("processing")

        wav_path = self._last_failed_wav
        ctx = self._last_failed_context or WindowContext()

        def worker():
            try:
                prompt = build_default_prompt(
                    application=ctx.application,
                    window_title=ctx.window_title,
                    language=self.settings.whisper_language,
                )
                res = self.transcriber.transcribe(
                    wav_path,
                    initial_prompt=prompt,
                    language=self.settings.whisper_language,
                )
                raw_text = res.text.strip()
                if not raw_text:
                    self.no_speech_detected.emit()
                    wav_path.unlink()
                    return

                rule_proc = RuleBasedTextProcessor()
                fast_proc_res = rule_proc.process(
                    raw_text,
                    context_app=ctx.application,
                    context_window=ctx.window_title,
                    language=self.settings.whisper_language,
                )
                fast_text_processed = (
                    fast_proc_res.text if (fast_proc_res.success and fast_proc_res.text != raw_text) else None
                )
                fast_category = fast_proc_res.category if fast_proc_res.success else None
                fast_tags = fast_proc_res.tags if fast_proc_res.success else []

                note = Note(
                    id=str(uuid.uuid4()),
                    captured_at_utc=ctx.captured_at_utc,
                    transcript=raw_text,
                    original_transcript=raw_text,
                    text_processed=fast_text_processed,
                    processed_by="rules" if fast_text_processed else None,
                    category=fast_category,
                    tags=fast_tags,
                    application=ctx.application,
                    window_title=ctx.window_title,
                )
                self.repository.save(note)
                wav_path.unlink()
                self._last_failed_wav = None
                self._last_failed_context = None
                self.transcription_finished.emit(note)

                if self.settings.refinement_engine == "llm":
                    note_id = note.id
                    app_name = ctx.application
                    win_title = ctx.window_title
                    lang = self.settings.whisper_language

                    def bg_llm_worker():
                        try:
                            llm_res = self.text_processor.process(
                                raw_text,
                                context_app=app_name,
                                context_window=win_title,
                                language=lang,
                            )
                            if llm_res.success:
                                refined_text = llm_res.text if llm_res.text != raw_text else None
                                updated = self.repository.update_processed_text(
                                    note_id,
                                    text_processed=refined_text or (fast_text_processed or ""),
                                    processed_by=llm_res.processor_id,
                                    category=llm_res.category or fast_category,
                                    tags=llm_res.tags or fast_tags,
                                )
                                if updated:
                                    self.note_refined.emit(updated)
                        except Exception as e:
                            logger.warning("Background LLM processing failed on retry: %s", e)

                    threading.Thread(target=bg_llm_worker, daemon=True).start()

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
        self.overlay.update_state("ready")

    # Slot Handlers
    @Slot()
    def _handle_recording_started(self) -> None:
        self.tray.update_state("recording")
        self.overlay.update_state("recording")
        self._show_tray_message(
            "Tucknote",
            f"🎙️ Recording...\nPress {self.config.hotkey_str} or overlay button to finish.",
            QSystemTrayIcon.Information,
            2000,
        )

    @Slot(object, object)
    def _handle_recording_stopped(self, wav_path: Path, ctx: WindowContext) -> None:
        self.tray.update_state("processing")
        self.overlay.update_state("processing")

    @Slot(object)
    def _handle_transcription_finished(self, note: Note) -> None:
        self.state = "ready"
        self.tray.update_state("ready")

        # Determine preferred text version for display / clipboard
        chosen_text = note.display_text(self.settings.default_text_version)

        # Auto-copy to clipboard if enabled in settings
        auto_copied = False
        if self.settings.auto_copy_clipboard and chosen_text:
            QApplication.clipboard().setText(chosen_text)
            auto_copied = True

        self.overlay.update_state("saved", result_text=chosen_text)

        # Refresh library if visible
        if self.library_window.isVisible():
            self.library_window.refresh_notes()

        preview = chosen_text
        if len(preview) > 60:
            preview = preview[:57] + "..."

        ctx_str = f" [{note.application}]" if note.application else ""
        copied_suffix = " (Copied to clipboard)" if auto_copied else ""

        self._show_tray_message(
            "Tucknote — Saved",
            f"✅{ctx_str} {preview}{copied_suffix}",
            QSystemTrayIcon.Information,
            3000,
        )

    @Slot(str, object, object)
    def _handle_transcription_failed(self, error_str: str, wav_path: Path, ctx: WindowContext) -> None:
        self.state = "error"
        self._last_failed_wav = wav_path
        self._last_failed_context = ctx
        self.tray.update_state("error", "Transcription error")
        self.overlay.update_state("error", detail_message="Transcription error")
        self._show_tray_message(
            "Tucknote — Error",
            f"Transcription failed: {error_str}\n"
            f"Audio preserved. Click 'Retry' or 'Discard' in tray menu.",
            QSystemTrayIcon.Critical,
            6000,
        )

    @Slot(object)
    def _handle_note_refined(self, note: Note) -> None:
        logger.info("Note %s asynchronously refined and categorized.", note.id)
        if self.library_window.isVisible():
            self.library_window.refresh_notes()
        if (
            self.settings.default_text_version == "processed"
            and self.settings.auto_copy_clipboard
            and note.text_processed
        ):
            current_clipboard = QApplication.clipboard().text()
            if current_clipboard in (note.transcript, note.original_transcript):
                QApplication.clipboard().setText(note.text_processed)

    @Slot()
    def _handle_no_speech_detected(self) -> None:
        self.state = "ready"
        self.tray.update_state("ready")
        self.overlay.update_state("ready")
        self._show_tray_message(
            "Tucknote",
            "No speech detected. Recording discarded.",
            QSystemTrayIcon.Warning,
            2500,
        )

    @Slot(str)
    def _handle_error_occurred(self, message: str) -> None:
        self.state = "ready"
        self.tray.update_state("ready")
        self.overlay.update_state("ready")
        self._show_tray_message(
            "Tucknote — Notice",
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
        self._poll_timer.stop()
        if self.state == "recording":
            self.recorder.cancel()
        self.hotkey_listener.stop()
        try:
            self.text_processor.stop()
        except Exception:
            pass
        self._cleanup_old_temp_recordings()
        QApplication.quit()
