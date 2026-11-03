"""Entry point: `python -m tgm`."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

import qasync
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigError, load_settings
from .tasks import spawn
from .ui import theme
from .ui.mainwindow import MainWindow


def main() -> int:
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("TG_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)

    app = QApplication(sys.argv)
    app.setApplicationName("tg-messenger-claude")
    app.setDesktopFileName("tg-messenger-claude")
    theme.apply(app)

    try:
        settings = load_settings()
    except ConfigError as exc:
        QMessageBox.critical(None, "Настройки", str(exc))
        return 2

    # Quitting Qt stops the asyncio loop under pending tasks; let main() return instead.
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow(settings)
    window.show()

    # Ctrl+C in the terminal closes the window the normal way. The timer lets Python see the signal.
    signal.signal(signal.SIGINT, lambda *_: window.close())
    tick = QTimer(interval=300, timeout=lambda: None)
    tick.start()

    async def run() -> None:
        done = asyncio.Event()
        window.finished.connect(done.set)
        app.aboutToQuit.connect(done.set)
        spawn(window.start())
        await done.wait()

    qasync.run(run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
