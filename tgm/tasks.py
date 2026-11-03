"""Fire-and-forget coroutines from Qt slots, with errors turned into readable text."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine

from telethon import errors

log = logging.getLogger(__name__)

_running: set[asyncio.Task] = set()
_error_sink: Callable[[str], None] | None = None


def set_error_sink(sink: Callable[[str], None]) -> None:
    global _error_sink
    _error_sink = sink


def spawn(coro: Coroutine, *, on_error: Callable[[str], None] | None = None, quiet: bool = False) -> asyncio.Task:
    task = asyncio.ensure_future(coro)
    _running.add(task)

    def done(t: asyncio.Task) -> None:
        _running.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is None:
            return
        log.warning("task failed: %s", describe_error(exc), exc_info=exc)
        if quiet:
            return
        sink = on_error or _error_sink
        if sink:
            sink(describe_error(exc))

    task.add_done_callback(done)
    return task


def describe_error(exc: BaseException) -> str:
    if isinstance(exc, errors.FloodWaitError):
        return f"Telegram просит подождать {exc.seconds} с"
    if isinstance(exc, errors.MessageNotModifiedError):
        return "Текст не изменился"
    if isinstance(exc, errors.MessageIdInvalidError):
        return "Сообщение больше недоступно"
    if isinstance(exc, (errors.ChatWriteForbiddenError, errors.UserIsBlockedError)):
        return "Писать в этот чат нельзя"
    if isinstance(exc, errors.PhoneCodeInvalidError):
        return "Неверный код"
    if isinstance(exc, errors.PhoneCodeExpiredError):
        return "Код устарел, запроси новый"
    if isinstance(exc, errors.PasswordHashInvalidError):
        return "Неверный пароль"
    if isinstance(exc, errors.PhoneNumberInvalidError):
        return "Неверный номер телефона"
    if isinstance(exc, (errors.UsernameNotOccupiedError, errors.UsernameInvalidError)):
        return "Пользователь не найден"
    if isinstance(exc, errors.RPCError):
        return f"Ошибка Telegram: {exc.message}"
    if isinstance(exc, (ConnectionError, OSError, asyncio.TimeoutError)):
        return "Нет соединения с Telegram"
    return str(exc) or type(exc).__name__
