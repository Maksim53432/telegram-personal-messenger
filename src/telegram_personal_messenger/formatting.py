"""Форматирование дат, имён и коротких подписей для интерфейса."""

from __future__ import annotations

import zlib
from datetime import date, datetime, timedelta

_MONTHS_SHORT = (
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)

_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

_AVATAR_COLORS = (
    "#E17076",
    "#7BC862",
    "#E5CA77",
    "#65AADD",
    "#A695E7",
    "#EE7AAE",
    "#6EC9CB",
    "#FAA774",
    "#7F8FA6",
    "#5CA5C9",
)


def format_chat_time(value: datetime | None, now: datetime | None = None) -> str:
    """Время последнего сообщения в списке чатов."""

    if value is None:
        return ""
    moment = _local(value)
    current = _local(now) if now is not None else datetime.now()
    if moment.date() == current.date():
        return f"{moment:%H:%M}"
    if moment.date() == current.date() - timedelta(days=1):
        return "Вчера"
    if moment.year == current.year:
        return f"{moment.day} {_MONTHS_SHORT[moment.month - 1]}"
    return f"{moment:%d.%m.%y}"


def format_message_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return f"{_local(value):%H:%M}"


def format_date_separator(value: datetime, now: datetime | None = None) -> str:
    """Подпись между группами сообщений: «Сегодня», «Вчера», «12 марта»."""

    moment = _local(value)
    current = _local(now) if now is not None else datetime.now()
    if moment.date() == current.date():
        return "Сегодня"
    if moment.date() == current.date() - timedelta(days=1):
        return "Вчера"
    if moment.year == current.year:
        return f"{moment.day} {_MONTHS_GENITIVE[moment.month - 1]}"
    return f"{moment.day} {_MONTHS_GENITIVE[moment.month - 1]} {moment.year}"


def day_key(value: datetime) -> date:
    return _local(value).date()


def initials(title: str) -> str:
    """Одна-две буквы для аватарки."""

    words = [word for word in title.replace("@", " ").split() if word]
    letters = [word[0] for word in words if word[0].isalnum()]
    if not letters:
        return "?"
    if len(letters) == 1:
        return letters[0].upper()
    return (letters[0] + letters[-1]).upper()


def avatar_color(seed: int | str) -> str:
    """Стабильный цвет аватарки для одного и того же чата."""

    index = zlib.crc32(str(seed).encode("utf-8")) % len(_AVATAR_COLORS)
    return _AVATAR_COLORS[index]


def preview(text: str, limit: int = 64) -> str:
    """Однострочный фрагмент последнего сообщения."""

    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(1, limit - 1)].rstrip() + "…"


def unread_text(count: int) -> str:
    if count <= 0:
        return ""
    return "99+" if count > 99 else str(count)


def plural(count: int, one: str, few: str, many: str) -> str:
    """Русское склонение по числу."""

    number = abs(count) % 100
    if 11 <= number <= 14:
        return many
    last = number % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def chats_word(count: int) -> str:
    return plural(count, "чат", "чата", "чатов")


def _local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone()
