"""Global Windows hotkey listener using RegisterHotKey and a dedicated message loop."""

from __future__ import annotations

import sys
import time
import logging
import threading
from typing import Callable

logger = logging.getLogger("tucknote")

# Win32 Constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

# Virtual key map for common hotkeys
VK_MAP = {
    "SPACE": 0x20,
    "F1": 0x70,
    "F2": 0x71,
    "F3": 0x72,
    "F4": 0x73,
    "F5": 0x74,
    "F6": 0x75,
    "F7": 0x76,
    "F8": 0x77,
    "F9": 0x78,
    "F10": 0x79,
    "F11": 0x7A,
    "F12": 0x7B,
}


class HotkeyRegistrationError(Exception):
    """Raised when registering the global hotkey fails."""

    def __init__(self, message: str, win_error_code: int = 0):
        super().__init__(message)
        self.win_error_code = win_error_code
        self.is_conflict = (win_error_code == ERROR_HOTKEY_ALREADY_REGISTERED)


class GlobalHotkeyListener:
    """Listens for a global Windows hotkey in a dedicated background thread."""

    def __init__(
        self,
        hotkey_str: str = "Ctrl+Alt+Space",
        on_triggered: Callable[[], None] | None = None,
        hotkey_id: int = 1001,
    ):
        self.hotkey_str = hotkey_str
        self.on_triggered = on_triggered
        self.hotkey_id = hotkey_id

        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._is_running = False
        self._reg_error: HotkeyRegistrationError | None = None
        self._init_event = threading.Event()
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._is_running

    def _parse_hotkey(self) -> tuple[int, int]:
        parts = [p.strip().upper() for p in self.hotkey_str.split("+")]
        modifiers = MOD_NOREPEAT
        key_name = parts[-1]

        for mod in parts[:-1]:
            if mod in ("CTRL", "CONTROL"):
                modifiers |= MOD_CONTROL
            elif mod == "ALT":
                modifiers |= MOD_ALT
            elif mod == "SHIFT":
                modifiers |= MOD_SHIFT
            elif mod in ("WIN", "WINDOWS"):
                modifiers |= MOD_WIN

        if key_name in VK_MAP:
            vk = VK_MAP[key_name]
        elif len(key_name) == 1 and key_name.isalnum():
            vk = ord(key_name)
        else:
            vk = 0x20  # Fallback to Space

        return modifiers, vk

    def start(self) -> None:
        """Start the hotkey listener thread and block until registration succeeds or fails."""
        if sys.platform != "win32":
            logger.warning("Global hotkeys via RegisterHotKey are only supported on Windows.")
            return

        with self._lock:
            if self._is_running:
                return

            self._reg_error = None
            self._init_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop, name="GlobalHotkeyThread", daemon=True
            )
            self._thread.start()

        # Wait for registration result
        if not self._init_event.wait(timeout=3.0):
            self.stop()
            raise HotkeyRegistrationError("Timed out waiting for hotkey registration thread.")

        if self._reg_error:
            self.stop()
            raise self._reg_error

    def _run_loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        self._thread_id = kernel32.GetCurrentThreadId()

        # Ensure thread has a message queue
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 0)

        modifiers, vk = self._parse_hotkey()

        # Register hotkey
        success = user32.RegisterHotKey(0, self.hotkey_id, modifiers, vk)
        if not success:
            err = ctypes.GetLastError()
            msg_str = (
                f"Hotkey '{self.hotkey_str}' is already registered by another application."
                if err == ERROR_HOTKEY_ALREADY_REGISTERED
                else f"Failed to register hotkey '{self.hotkey_str}' (Win32 error {err})."
            )
            logger.error(msg_str)
            self._reg_error = HotkeyRegistrationError(msg_str, win_error_code=err)
            self._init_event.set()
            return

        with self._lock:
            self._is_running = True

        logger.info("Global hotkey '%s' registered successfully.", self.hotkey_str)
        self._init_event.set()

        try:
            # Win32 Message Loop
            while user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.hotkey_id:
                    logger.debug("WM_HOTKEY received for ID %s.", self.hotkey_id)
                    if self.on_triggered:
                        try:
                            self.on_triggered()
                        except Exception as e:
                            logger.error("Error in hotkey trigger callback: %s", e)
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(0, self.hotkey_id)
            with self._lock:
                self._is_running = False
            logger.info("Global hotkey '%s' unregistered.", self.hotkey_str)

    def stop(self) -> None:
        """Stop the hotkey listener thread cleanly."""
        if sys.platform != "win32":
            return

        with self._lock:
            if not self._is_running and (not self._thread or not self._thread.is_alive()):
                return

        if self._thread_id:
            import ctypes
            user32 = ctypes.windll.user32
            # Post WM_QUIT to break GetMessage loop
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        with self._lock:
            self._thread = None
            self._thread_id = None
            self._is_running = False
