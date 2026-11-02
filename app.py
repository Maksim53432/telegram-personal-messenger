#!/usr/bin/env python3
"""Запуск графического клиента Telegram."""

from __future__ import annotations

import logging
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from telegram_personal_messenger.async_worker import AsyncWorker
from telegram_personal_messenger.config import (
    CredentialError,
    Settings,
    default_env_path,
    load_settings,
)
from telegram_personal_messenger.telegram_service import TelegramService
from telegram_personal_messenger.ui import MainWindow, SetupView, Theme

logger = logging.getLogger("app")


def _enable_high_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def main() -> None:
    _enable_high_dpi()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)

    root = tk.Tk()
    theme = Theme(root)
    env_path = default_env_path()

    try:
        settings = load_settings(env_path)
    except CredentialError as exc:
        _show_setup(root, theme, env_path, exc)
        root.mainloop()
        return
    except (OSError, ValueError) as exc:
        logger.warning("Не удалось загрузить настройки: %s", type(exc).__name__)
        messagebox.showerror(
            "Ошибка настроек",
            "Не удалось загрузить настройки Telegram. "
            "Проверь файл .env и права на папку проекта.",
            parent=root,
        )
        root.destroy()
        return

    app = _create_app(root, theme, settings, env_path)
    if app is not None:
        root.mainloop()


def _show_setup(
    root: tk.Tk,
    theme: Theme,
    env_path: Path,
    error: Exception,
) -> None:
    root.title("Telegram — настройка")
    root.geometry("640x760")
    root.minsize(560, 680)

    def on_saved(settings: Settings) -> None:
        for child in root.winfo_children():
            child.destroy()
        root.title("Telegram — личный клиент")
        _create_app(root, theme, settings, env_path)

    setup = SetupView(
        root,
        theme,
        env_path,
        on_saved,
        root.destroy,
    )
    setup.pack(fill="both", expand=True)
    logger.info("Показана настройка API: %s", type(error).__name__)


def _create_app(
    root: tk.Tk,
    theme: Theme,
    settings: Settings,
    env_path: Path,
) -> MainWindow | None:
    worker = AsyncWorker()
    try:
        service = TelegramService(settings)
    except Exception as exc:
        logger.warning("Не удалось создать клиент Telegram: %s", type(exc).__name__)
        worker.close()
        messagebox.showerror(
            "Ошибка подключения",
            "Не удалось создать клиент Telegram. Проверь настройки и попробуй снова.",
            parent=root,
        )
        root.destroy()
        return None

    try:
        window = MainWindow(root, theme, service, worker, settings, env_path)
    except Exception as exc:
        logger.warning("Не удалось открыть окно клиента: %s", type(exc).__name__)
        worker.close()
        messagebox.showerror(
            "Ошибка интерфейса",
            "Не удалось открыть окно клиента. Перезапусти приложение.",
            parent=root,
        )
        root.destroy()
        return None

    setattr(root, "_telegram_app", window)
    return window


if __name__ == "__main__":
    main()
