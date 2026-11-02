"""Доменные модели клиента Telegram.

Модели не зависят от Tkinter и Telethon: сервисный слой переводит объекты
Telethon в эти структуры, а интерфейс работает только с ними.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

MAX_MESSAGE_LENGTH = 4096

ChatKind = Literal["user", "bot", "group", "channel"]
FolderKind = Literal["all", "archive", "custom"]
OutcomeKind = Literal["sent", "failed", "unknown"]


@dataclass(frozen=True, slots=True)
class Account:
    """Текущий авторизованный аккаунт."""

    id: int
    display_name: str
    username: str | None = None

    @property
    def handle(self) -> str:
        return f"@{self.username}" if self.username else ""


@dataclass(frozen=True, slots=True)
class Chat:
    """Строка списка чатов."""

    id: int
    title: str
    username: str | None = None
    kind: ChatKind = "user"
    last_message: str = ""
    last_out: bool = False
    date: datetime | None = None
    unread: int = 0
    pinned: bool = False
    archived: bool = False
    muted: bool = False
    is_contact: bool = False

    @property
    def is_user(self) -> bool:
        return self.kind in ("user", "bot")

    @property
    def is_bot(self) -> bool:
        return self.kind == "bot"

    @property
    def is_group(self) -> bool:
        return self.kind == "group"

    @property
    def is_channel(self) -> bool:
        return self.kind == "channel"


@dataclass(frozen=True, slots=True)
class Message:
    """Одно сообщение в переписке."""

    id: int
    chat_id: int
    text: str
    date: datetime
    out: bool = False
    sender_name: str = ""
    media: str | None = None
    reply_to: int | None = None

    @property
    def is_empty(self) -> bool:
        return not self.text and not self.media


@dataclass(frozen=True, slots=True)
class Folder:
    """Папка чатов: «Все», «Архив» или пользовательский фильтр."""

    key: str
    title: str
    kind: FolderKind = "custom"
    id: int | None = None
    pinned_peers: frozenset[int] = field(default_factory=frozenset)
    include_peers: frozenset[int] = field(default_factory=frozenset)
    exclude_peers: frozenset[int] = field(default_factory=frozenset)
    contacts: bool = False
    non_contacts: bool = False
    groups: bool = False
    broadcasts: bool = False
    bots: bool = False
    exclude_muted: bool = False
    exclude_read: bool = False
    exclude_archived: bool = False
    emoticon: str | None = None


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """Результат одной попытки отправки сообщения."""

    kind: OutcomeKind
    code: str = ""
    sent_message: Message | None = None
    seconds: int | None = None


class MessageValidationError(ValueError):
    """Текст сообщения не прошёл локальную проверку."""

    def __init__(self, code: Literal["empty", "too_long"]) -> None:
        super().__init__(code)
        self.code = code


def validate_message(text: str) -> str:
    """Проверяет текст перед отправкой, не меняя его содержимое.

    Пустые сообщения и сообщения длиннее лимита Telegram отклоняются
    локально; разбивать текст на части приложение не должно.
    """

    if not text.strip():
        raise MessageValidationError("empty")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise MessageValidationError("too_long")
    return text


# Совместимый алиас для внешнего кода, который ещё мог импортировать Recipient.
Recipient = Chat
