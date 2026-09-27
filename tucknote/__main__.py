"""Main CLI entrypoint for Thought Capture (tucknote)."""

from __future__ import annotations

import sys
import argparse
from PySide6.QtWidgets import QApplication

from tucknote.config import AppConfig, setup_logging, APP_DISPLAY_NAME
from tucknote.ui.app import StateCoordinator


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="tucknote",
        description="Thought Capture — Voice thoughts with window context on Windows.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Whisper model to use (default: 'base', or 'tiny', 'small', etc.)",
    )
    parser.add_argument(
        "--hotkey",
        type=str,
        default=None,
        help="Custom global hotkey (default: 'Ctrl+Alt+Space')",
    )
    parser.add_argument(
        "--show-library",
        action="store_true",
        help="Immediately open the Library window on startup",
    )
    args = parser.parse_args()

    config = AppConfig()
    if args.model:
        config.whisper_model = args.model
    if args.hotkey:
        config.hotkey_str = args.hotkey

    logger = setup_logging(config)
    logger.info("Starting %s...", APP_DISPLAY_NAME)

    # Initialize Qt Application
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)

    app.setApplicationName("tucknote")
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    # Essential for background tray apps: don't quit when library window closes!
    app.setQuitOnLastWindowClosed(False)

    coordinator = StateCoordinator(config)
    coordinator.start()

    if args.show_library:
        coordinator.open_library()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
