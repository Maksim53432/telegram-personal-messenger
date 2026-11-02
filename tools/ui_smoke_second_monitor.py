#!/usr/bin/env python3
"""Визуальный smoke-тест клиента на втором мониторе.

Запуск из корня проекта:

    python tools/ui_smoke_second_monitor.py
    python tools/ui_smoke_second_monitor.py --screenshot docs/ui-second.png

Окно создаётся прозрачным, перемещается через Mango IPC, и только после
подтверждения второго монитора становится видимым. Фокус возвращается игре
на основном мониторе. Данные — фейковые, Telegram не используется.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from second_monitor import SecondMonitorError, place_tk_window  # noqa: E402
from telegram_personal_messenger.async_worker import AsyncWorker  # noqa: E402
from telegram_personal_messenger.config import Settings  # noqa: E402
from telegram_personal_messenger.models import (  # noqa: E402
    Account,
    Chat,
    Folder,
    Message,
    SendOutcome,
)
from telegram_personal_messenger.ui import MainWindow, Theme  # noqa: E402


def minutes_ago(minutes: int = 0) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


class FakeService:
    async def is_authorized(self) -> bool:
        return True

    async def get_me(self) -> Account:
        return Account(1, "Максим", "max")

    async def list_folders(self) -> list[Folder]:
        return [
            Folder("all", "Все чаты", "all"),
            Folder("archive", "Архив", "archive"),
            Folder("folder:2", "Работа", "custom", id=2, groups=True),
            Folder("folder:3", "Личное", "custom", id=3, contacts=True),
        ]

    async def list_chats(self) -> list[Chat]:
        return [
            Chat(10, "Аня Соколова", "anya", "user", "Тогда до встречи завтра :)", False, minutes_ago(2), 2, False, False, False, True),
            Chat(11, "Команда дизайна", "design", "group", "Максим: выложил новые макеты", True, minutes_ago(18), 0, True, False, False, False),
            Chat(12, "Telegram", "telegram", "channel", "Обновление приложения", False, minutes_ago(60), 1, False, False, True, False),
            Chat(13, "Рабочий чат", None, "group", "Недельный созвон в 11:00", False, minutes_ago(180), 0, False, False, False, False),
            Chat(14, "Павел", "pavel", "user", "Спасибо!", False, minutes_ago(60 * 26), 0, False, False, False, True),
            Chat(15, "Архивный чат", None, "group", "старое сообщение", False, minutes_ago(60 * 24 * 30), 0, False, True, False, False),
        ]

    async def get_messages(
        self,
        chat_id: int,
        limit: int = 60,
        offset_id: int = 0,
    ) -> list[Message]:
        base = minutes_ago(240)
        rows = [
            (False, "Аня Соколова", "Привет! Ты уже посмотрел макеты?"),
            (True, "", "Да, глянул. Выглядит намного чище."),
            (False, "Павел", "Отлично. Осталось поправить пару отступов."),
            (True, "", "Скинь список, я поправлю."),
            (False, "Аня Соколова", "Тогда до встречи завтра :)"),
        ]
        return [
            Message(
                i + 1,
                chat_id,
                text,
                base + timedelta(minutes=i * 7),
                out,
                sender,
            )
            for i, (out, sender, text) in enumerate(rows)
        ]

    async def send_message(self, chat_id: int, text: str) -> SendOutcome:
        return SendOutcome(
            "sent",
            "sent",
            Message(999, chat_id, text, datetime.now(timezone.utc), True),
        )

    async def mark_read(self, chat_id: int) -> None:
        return None

    async def resolve_username(self, username: str) -> Chat:
        return Chat(77, "Новый человек", username, "user", is_contact=False)

    async def download_avatar(self, chat_id: int, file: str | None = None):
        return None

    async def download_media(self, chat_id: int, message_id: int, thumb=None, file=None):
        return None

    def start_listening(self, callback) -> None:
        self.callback = callback

    async def disconnect(self) -> None:
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=4.0)
    args = parser.parse_args()

    root = tk.Tk(className="TpmUiTest")
    root.title("Telegram UI test")
    root.attributes("-alpha", 0.0)
    root.geometry("1180x760")
    worker = AsyncWorker()
    window = MainWindow(
        root,
        Theme(root),
        FakeService(),
        worker,
        Settings(1, "a" * 32, Path("/tmp/tpm-session")),
        Path("/tmp/tpm.env"),
    )

    def placed() -> None:
        try:
            info = place_tk_window(root, show=True, restore_focus=True)
        except Exception as error:
            print(f"Не удалось переместить окно: {error}", flush=True)
            root.destroy()
            return
        print(
            f"Окно на {info.monitor}: {info.width}x{info.height}"
            f"+{info.x}+{info.y}, тег {info.tags}",
            flush=True,
        )
        root.after(int(args.seconds * 1000), window.close)

    root.after(1500, placed)
    root.mainloop()


if __name__ == "__main__":
    main()
