"""Tests for GlobalHotkeyListener."""

import sys
import pytest
from tucknote.hotkey.listener import (
    GlobalHotkeyListener,
    MOD_ALT,
    MOD_CONTROL,
    MOD_SHIFT,
    MOD_WIN,
    MOD_NOREPEAT,
    VK_MAP,
)


def test_hotkey_parsing():
    l1 = GlobalHotkeyListener("Ctrl+Alt+Space")
    mods, vk = l1._parse_hotkey()
    assert mods == (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT)
    assert vk == 0x20

    l2 = GlobalHotkeyListener("Ctrl+Shift+F9")
    mods2, vk2 = l2._parse_hotkey()
    assert mods2 == (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT)
    assert vk2 == VK_MAP["F9"]

    l3 = GlobalHotkeyListener("Win+Alt+R")
    mods3, vk3 = l3._parse_hotkey()
    assert mods3 == (MOD_WIN | MOD_ALT | MOD_NOREPEAT)
    assert vk3 == ord("R")


def test_listener_lifecycle_windows():
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    # Use a non-reserved hotkey combination
    listener = GlobalHotkeyListener(hotkey_str="Ctrl+Alt+Shift+F7", hotkey_id=9998)
    try:
        listener.start()
        assert listener.is_running is True
    finally:
        listener.stop()
        assert listener.is_running is False


def test_hotkey_conflict_detection():
    if sys.platform != "win32":
        pytest.skip("Windows-only test")

    from tucknote.hotkey.listener import HotkeyRegistrationError

    # Ctrl+Alt+F12 is commonly reserved by Intel graphics driver
    listener = GlobalHotkeyListener(hotkey_str="Ctrl+Alt+F12", hotkey_id=9997)
    try:
        listener.start()
    except HotkeyRegistrationError as exc:
        assert exc.is_conflict is True
    finally:
        listener.stop()
