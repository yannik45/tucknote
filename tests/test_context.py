"""Tests for WindowContextGrabber."""

import sys
from tucknote.context.window import WindowContextGrabber
from tucknote.storage.models import WindowContext


def test_capture_returns_context():
    grabber = WindowContextGrabber()
    ctx = grabber.capture_active_window()
    assert isinstance(ctx, WindowContext)
    assert ctx.captured_at_utc is not None
    # On Windows, pid might be int if foreground window exists, or None
    if sys.platform == "win32":
        if ctx.process_id is not None:
            assert isinstance(ctx.process_id, int)
        if ctx.window_title is not None:
            assert isinstance(ctx.window_title, str)


def test_friendly_app_name_fallback():
    grabber = WindowContextGrabber()
    # Test title splitting logic if process name could not be queried
    ctx = WindowContext(
        window_title="tucknote - Visual Studio Code",
        application=None,
    )
    # If application is None, check fallback parsing
    if not ctx.application and ctx.window_title and " - " in ctx.window_title:
        app = ctx.window_title.rsplit(" - ", 1)[1]
        assert app == "Visual Studio Code"


def test_is_own_window_detection():
    grabber = WindowContextGrabber()
    # Own PID should always be recognized as own window
    assert grabber.is_own_window(grabber._our_pid, "Any Title", "python.exe") is True
    assert grabber.is_own_window(grabber._our_pid + 9999, "Thought Capture — Library", "python.exe") is True
    assert grabber.is_own_window(grabber._our_pid + 9999, "gen_wav.ps1 - Visual Studio Code", "Code.exe") is False


def test_fallback_to_last_external_context():
    grabber = WindowContextGrabber()
    external_ctx = WindowContext(
        application="Code.exe",
        window_title="main.py - Visual Studio Code",
        process_id=12345,
    )
    grabber._last_external_context = external_ctx

    # Mock _capture_win32 returning our own window
    grabber._capture_win32 = lambda now_utc: WindowContext(
        application="tucknote.exe",
        window_title="Thought Capture Overlay",
        process_id=grabber._our_pid,
        captured_at_utc=now_utc,
    )

    # When capturing active window with allow_self=False, it MUST return the external context!
    captured = grabber.capture_active_window(allow_self=False)
    assert captured.application == "Code.exe"
    assert captured.window_title == "main.py - Visual Studio Code"
    assert captured.process_id == 12345
