"""Date and time strings."""

from __future__ import annotations

from datetime import date, datetime

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]


def local(dt: datetime) -> datetime:
    return dt.astimezone()


def list_time(dt: datetime, now: datetime | None = None) -> str:
    """Chat list: time today, weekday this week, date otherwise."""
    dt = local(dt)
    now = now or datetime.now().astimezone()
    days = (now.date() - dt.date()).days
    if days <= 0:
        return dt.strftime("%H:%M")
    if days < 7:
        return WEEKDAYS[dt.weekday()]
    return dt.strftime("%d.%m.%y")


def day_title(d: date, today: date | None = None) -> str:
    today = today or date.today()
    days = (today - d).days
    if days == 0:
        return "Сегодня"
    if days == 1:
        return "Вчера"
    text = f"{d.day} {MONTHS[d.month - 1]}"
    return text if d.year == today.year else f"{text} {d.year}"


def clock(dt: datetime) -> str:
    return local(dt).strftime("%H:%M")
