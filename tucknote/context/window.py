"""Windows foreground window and process context capture with external window tracking."""

from __future__ import annotations

import sys
import os
import logging
from pathlib import Path
from datetime import datetime, timezone

from tucknote.storage.models import WindowContext

logger = logging.getLogger("tucknote")

# Win32 Constants
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
DESKTOP_SWITCHDESKTOP = 0x0100
GENERIC_ALL = 0x10000000
DESKTOP_ACCESS = 0x01FF


class WindowContextGrabber:
    """Captures the active foreground window title and application name via Win32 APIs.
    
    Includes tracking to ensure clicking the Tucknote overlay does not accidentally
    record Tucknote itself as the active application.
    """

    def __init__(self):
        self._is_windows = sys.platform == "win32"
        self._our_pid = os.getpid()
        self._last_external_context: WindowContext | None = None

        if self._is_windows:
            import ctypes
            from ctypes import wintypes

            self._ctypes = ctypes
            self._wintypes = wintypes
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32

    @property
    def last_external_context(self) -> WindowContext | None:
        return self._last_external_context

    def is_own_window(self, pid: int | None, window_title: str | None, app_name: str | None) -> bool:
        """Determine if a window belongs to the Thought Capture / tucknote process."""
        if pid is not None and pid == self._our_pid:
            return True
        if window_title and ("Thought Capture" in window_title or "tucknote" in window_title.lower()):
            if app_name and app_name.lower() in ("python.exe", "pythonw.exe", "tucknote.exe"):
                return True
        return False

    def poll_external_window(self) -> WindowContext | None:
        """Background poll called periodically to keep track of the last external application."""
        if not self._is_windows:
            return None
        try:
            ctx = self._capture_win32(datetime.now(timezone.utc).isoformat())
            if ctx.process_id and not self.is_own_window(ctx.process_id, ctx.window_title, ctx.application):
                self._last_external_context = ctx
                return ctx
        except Exception:
            pass
        return self._last_external_context

    def capture_active_window(self, allow_self: bool = False) -> WindowContext:
        """Capture the foreground window context immediately before any app focus change.
        
        If allow_self is False and the currently focused window is Tucknote (e.g. user
        just clicked the overlay), it returns the last active external window instead.
        """
        now_utc = datetime.now(timezone.utc).isoformat()

        if not self._is_windows:
            logger.debug("Non-Windows OS: returning empty window context.")
            return WindowContext(captured_at_utc=now_utc)

        try:
            ctx = self._capture_win32(now_utc)

            # Check if this is our own window (e.g. user clicked overlay button)
            if not allow_self and self.is_own_window(ctx.process_id, ctx.window_title, ctx.application):
                if self._last_external_context:
                    logger.debug(
                        "Active window is Tucknote (%s); falling back to last external context: %s (%s)",
                        ctx.window_title,
                        self._last_external_context.application,
                        self._last_external_context.window_title,
                    )
                    # Return a copy with fresh timestamp
                    return WindowContext(
                        application=self._last_external_context.application,
                        window_title=self._last_external_context.window_title,
                        process_id=self._last_external_context.process_id,
                        process_path=self._last_external_context.process_path,
                        captured_at_utc=now_utc,
                    )

            if not self.is_own_window(ctx.process_id, ctx.window_title, ctx.application) and (ctx.process_id or ctx.window_title):
                self._last_external_context = ctx

            return ctx
        except Exception as exc:
            logger.warning("Error capturing active window context: %s", exc)
            if self._last_external_context and not allow_self:
                return WindowContext(
                    application=self._last_external_context.application,
                    window_title=self._last_external_context.window_title,
                    process_id=self._last_external_context.process_id,
                    process_path=self._last_external_context.process_path,
                    captured_at_utc=now_utc,
                )
            return WindowContext(captured_at_utc=now_utc)

    def _capture_win32(self, now_utc: str) -> WindowContext:
        user32 = self._user32
        kernel32 = self._kernel32
        ctypes = self._ctypes
        wintypes = self._wintypes

        # 1. Get foreground window handle
        hwnd = user32.GetForegroundWindow()

        # In case the current thread is attached to a non-interactive desktop,
        # try opening the interactive "Default" desktop.
        if not hwnd:
            try:
                hdesk = user32.OpenDesktopW("Default", 0, False, DESKTOP_ACCESS)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)
                    hwnd = user32.GetForegroundWindow()
            except Exception:
                pass

        if not hwnd:
            logger.debug("No foreground window detected.")
            return WindowContext(captured_at_utc=now_utc)

        # 2. Extract window title
        window_title: str | None = None
        try:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title_val = buf.value.strip()
                if title_val:
                    window_title = title_val
        except Exception as e:
            logger.debug("Failed to retrieve window text: %s", e)

        # 3. Extract Process ID
        pid_val: int | None = None
        try:
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value > 0:
                pid_val = pid.value
        except Exception as e:
            logger.debug("Failed to get process ID for hwnd: %s", e)

        # 4. Extract Application executable name and full path
        app_name: str | None = None
        exe_path: str | None = None

        if pid_val:
            try:
                h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_val)
                if h_proc:
                    try:
                        exe_buf = ctypes.create_unicode_buffer(1024)
                        size = wintypes.DWORD(1024)
                        if kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                            exe_path = exe_buf.value
                            if exe_path:
                                app_name = Path(exe_path).name
                    finally:
                        kernel32.CloseHandle(h_proc)
            except Exception as e:
                logger.debug("Failed to query process image name: %s", e)

        # Friendly fallback if process name is unknown but window title exists
        if not app_name and window_title:
            if " - " in window_title:
                parts = window_title.rsplit(" - ", 1)
                if len(parts) == 2 and len(parts[1]) < 40:
                    app_name = parts[1]

        return WindowContext(
            application=app_name,
            window_title=window_title,
            process_id=pid_val,
            process_path=exe_path,
            captured_at_utc=now_utc,
        )
