"""Состояние списка чатов, не зависящее от Tkinter.

ChatStore хранит загруженные чаты и папки, применяет поиск, считает
непрочитанные и обновляет превью при входящих сообщениях. Благодаря этому
логику списка можно тестировать без запуска окна.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .folders import (
    ALL_FOLDER_KEY,
    all_folder,
    archive_folder,
    chats_in_folder,
)
from .formatting import preview
from .models import Chat, Folder, Message


class ChatStore:
    def __init__(
        self,
        chats: list[Chat] | None = None,
        folders: list[Folder] | None = None,
    ) -> None:
        self._chats: dict[int, Chat] = {}
        if chats:
            self._chats = {chat.id: chat for chat in chats}
        self._folders = _with_default_folders(folders or [])
        self._folder_key = ALL_FOLDER_KEY
        self._query = ""
        self._selected_id: int | None = None

    @property
    def chats(self) -> list[Chat]:
        return list(self._chats.values())

    @property
    def folders(self) -> list[Folder]:
        return list(self._folders)

    @property
    def folder_key(self) -> str:
        return self._folder_key

    @property
    def query(self) -> str:
        return self._query

    @property
    def selected_id(self) -> int | None:
        return self._selected_id

    @property
    def selected(self) -> Chat | None:
        if self._selected_id is None:
            return None
        return self._chats.get(self._selected_id)

    def chat(self, chat_id: int) -> Chat | None:
        return self._chats.get(chat_id)

    def folder(self, key: str | None = None) -> Folder:
        wanted = key or self._folder_key
        for folder in self._folders:
            if folder.key == wanted:
                return folder
        return self._folders[0]

    def load(self, chats: list[Chat], folders: list[Folder]) -> None:
        """Заменяет данные, сохраняя выбранный чат и активную папку."""

        self._chats = {chat.id: chat for chat in chats}
        self._folders = _with_default_folders(folders)
        keys = {folder.key for folder in self._folders}
        if self._folder_key not in keys:
            self._folder_key = ALL_FOLDER_KEY
        if self._selected_id not in self._chats:
            self._selected_id = None

    def add_chat(self, chat: Chat) -> None:
        """Добавляет чат, найденный по @username, или обновляет старый."""

        if chat.date is None:
            chat = replace(chat, date=datetime.now())
        self._chats[chat.id] = chat

    def set_folder(self, key: str) -> None:
        if any(folder.key == key for folder in self._folders):
            self._folder_key = key

    def set_query(self, query: str) -> None:
        self._query = query

    def select(self, chat_id: int | None) -> None:
        if chat_id is None or chat_id in self._chats:
            self._selected_id = chat_id

    def visible_chats(self) -> list[Chat]:
        folder = self.folder()
        chats = chats_in_folder(folder, list(self._chats.values()))
        query = self._query.strip().lstrip("@").casefold()
        if not query:
            return chats
        return [
            chat
            for chat in chats
            if query in chat.title.casefold()
            or (chat.username is not None and query in chat.username.casefold())
        ]

    def folder_counts(self) -> dict[str, int]:
        counts = {}
        for folder in self._folders:
            counts[folder.key] = len(
                chats_in_folder(folder, list(self._chats.values()))
            )
        return counts

    def unread_total(self) -> int:
        return sum(chat.unread for chat in self._chats.values())

    def mark_read(self, chat_id: int) -> bool:
        chat = self._chats.get(chat_id)
        if chat is None or chat.unread == 0:
            return False
        self._chats[chat_id] = replace(chat, unread=0)
        return True

    def apply_message(self, message: Message) -> bool:
        """Обновляет превью и счётчик непрочитанных по новому сообщению."""

        chat = self._chats.get(message.chat_id)
        if chat is None:
            return False

        if message.out or self._selected_id == chat.id:
            unread = 0
        else:
            unread = chat.unread + 1

        self._chats[chat.id] = replace(
            chat,
            last_message=message_preview(message),
            last_out=message.out,
            date=message.date,
            unread=unread,
        )
        return True


def message_preview(message: Message) -> str:
    """Короткая подпись сообщения для строки чата."""

    text = " ".join((message.text or "").split())
    if message.media:
        text = f"{message.media} · {text}" if text else message.media
    return preview(text, limit=80)


def _with_default_folders(folders: list[Folder]) -> list[Folder]:
    result = list(folders)
    if not any(folder.kind == "all" for folder in result):
        result.insert(0, all_folder())
    if not any(folder.kind == "archive" for folder in result):
        index = 1 if result and result[0].kind == "all" else len(result)
        result.insert(index, archive_folder())
    return result
