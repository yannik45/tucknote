"""Windows foreground window and process context capture."""

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
    """Captures the active foreground window title and application name via Win32 APIs."""

    def __init__(self):
        self._is_windows = sys.platform == "win32"
        if self._is_windows:
            import ctypes
            from ctypes import wintypes

            self._ctypes = ctypes
            self._wintypes = wintypes
            self._user32 = ctypes.windll.user32
            self._kernel32 = ctypes.windll.kernel32

    def capture_active_window(self) -> WindowContext:
        """Capture the foreground window context immediately before any app focus change.
        
        Returns WindowContext with whatever fields could be safely retrieved;
        missing/inaccessible fields remain None.
        """
        now_utc = datetime.now(timezone.utc).isoformat()

        if not self._is_windows:
            logger.debug("Non-Windows OS: returning empty window context.")
            return WindowContext(captured_at_utc=now_utc)

        try:
            return self._capture_win32(now_utc)
        except Exception as exc:
            logger.warning("Error capturing active window context: %s", exc)
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
            # Check if there is a known suffix like " - Visual Studio Code"
            if " - " in window_title:
                parts = window_title.rsplit(" - ", 1)
                if len(parts) == 2 and len(parts[1]) < 40:
                    app_name = parts[1]

        logger.debug(
            "Captured window context: app='%s', title='%s', pid=%s",
            app_name,
            window_title[:30] if window_title else None,
            pid_val,
        )

        return WindowContext(
            application=app_name,
            window_title=window_title,
            process_id=pid_val,
            process_path=exe_path,
            captured_at_utc=now_utc,
        )
