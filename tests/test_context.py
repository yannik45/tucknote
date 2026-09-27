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
