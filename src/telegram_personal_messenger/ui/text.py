"""Русские подписи для интерфейса и перевод кодов ошибок."""

from __future__ import annotations

from .. import errors
from ..formatting import plural, preview
from ..models import Account, Chat, SendOutcome

_DEFAULT_ERROR = "Не удалось выполнить запрос. Проверь подключение и попробуй ещё раз."

_ERRORS = {
    errors.CONNECTION: "Не удалось подключиться к Telegram. Проверь интернет и попробуй ещё раз.",
    errors.LOGIN_SEND_CODE: "Не удалось отправить код. Проверь номер телефона и попробуй ещё раз.",
    errors.LOGIN_PHONE_INVALID: "Проверь номер телефона: нужен код страны, например +7 999 123-45-67.",
    errors.LOGIN_CODE_INVALID: "Код из Telegram не подошёл. Проверь его и попробуй ещё раз.",
    errors.LOGIN_CODE_EXPIRED: "Срок действия кода истёк. Запроси новый код.",
    errors.LOGIN_REJECTED: "Telegram отклонил вход. Проверь данные и попробуй ещё раз.",
    errors.LOGIN_PASSWORD_INVALID: "Пароль двухэтапной проверки не подошёл.",
    errors.LOGIN_PASSWORD_REJECTED: "Telegram не принял пароль двухэтапной проверки.",
    errors.USERNAME_INVALID: "Введи один полный @username без пробелов.",
    errors.USERNAME_NOT_FOUND: "Не нашёл такой @username. Проверь написание и доступность аккаунта.",
    errors.NOT_A_PERSON: "Это не личный аккаунт. Выбери человека, а не группу или канал.",
    errors.DIALOGS_FAILED: "Не удалось загрузить чаты. Проверь интернет и обнови список.",
    errors.MESSAGES_FAILED: "Не удалось загрузить сообщения. Проверь интернет и попробуй ещё раз.",
    errors.SEND_REJECTED: "Telegram не принял сообщение. Проверь чат и ограничения аккаунта.",
    errors.SEND_UNKNOWN: "Результат неизвестен: сообщение могло уйти. Приложение не повторяло отправку.",
    errors.SEND_FAILED: "Не удалось отправить сообщение. Проверь интернет и попробуй ещё раз.",
    errors.NOT_AUTHORIZED: "Аккаунт не авторизован. Войди в Telegram заново.",
    errors.ACTION_FAILED: "Не удалось выполнить действие. Попробуй ещё раз.",
}


def error_text(error: Exception | str, seconds: int | None = None) -> str:
    code = error
    if not isinstance(error, str):
        code = getattr(error, "code", "")
        if seconds is None:
            seconds = getattr(error, "seconds", None)
    if code == errors.FLOOD_WAIT:
        return f"Telegram просит подождать: {_wait_phrase(seconds)}."
    return _ERRORS.get(str(code), _DEFAULT_ERROR)


def outcome_text(outcome: SendOutcome) -> str:
    if outcome.kind == "sent":
        return "Сообщение отправлено."
    if outcome.kind == "unknown":
        return error_text(errors.SEND_UNKNOWN)
    code = outcome.code or errors.SEND_FAILED
    if code == errors.FLOOD_WAIT:
        return f"Telegram просит подождать: {_wait_phrase(outcome.seconds)}."
    if code == "empty":
        return "Сначала введи текст сообщения."
    if code == "too_long":
        return "Сообщение длиннее 4096 символов. Telegram не принимает такие сообщения."
    return _ERRORS.get(code, _DEFAULT_ERROR)


def chat_subtitle(chat: Chat) -> str:
    if chat.is_bot:
        label = "Бот"
    elif chat.is_group:
        label = "Группа"
    elif chat.is_channel:
        label = "Канал"
    elif chat.username:
        return f"@{chat.username}"
    else:
        label = "Личный чат"
    if chat.archived:
        label += " · архив"
    return label


def last_message_line(chat: Chat) -> str:
    if not chat.last_message:
        return "Нет сообщений"
    prefix = "Вы: " if chat.last_out else ""
    return prefix + chat.last_message


def account_handle(account: Account | None) -> str:
    if account is None:
        return ""
    return account.handle


def account_title(account: Account | None) -> str:
    return account.display_name if account is not None else "Аккаунт"


def message_counter(length: int, limit: int) -> str:
    return f"{length} / {limit}"


def short_username(query: str) -> str:
    value = query.strip()
    if value.startswith("@"):
        value = value[1:]
    return preview(value, 32)


def _wait_phrase(seconds: int | None) -> str:
    if not seconds or seconds <= 0:
        return "немного"
    if seconds < 60:
        return f"{seconds} {plural(seconds, 'секунду', 'секунды', 'секунд')}"
    minutes = (seconds + 59) // 60
    return f"{minutes} {plural(minutes, 'минуту', 'минуты', 'минут')}"
