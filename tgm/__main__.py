"""Entry point: `python -m tgm`."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

import qasync
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

    window = MainWindow(settings)
    window.show()

    async def run() -> None:
        closed = asyncio.Event()
        app.aboutToQuit.connect(closed.set)
        spawn(window.start())
        await closed.wait()

    try:
        qasync.run(run())
    except asyncio.CancelledError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
