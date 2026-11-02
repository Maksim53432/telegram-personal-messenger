"""Безопасные коды ошибок сервисного слоя.

Сервис не бросает наружу тексты Telethon: они могут содержать детали,
которые не нужно показывать или логировать. Интерфейс переводит коды
в понятные русские подписи.
"""

from __future__ import annotations


class TelegramServiceError(Exception):
    """Операция с Telegram завершилась ошибкой."""

    def __init__(self, code: str, *, seconds: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.seconds = seconds


CONNECTION = "connection"
LOGIN_SEND_CODE = "login_send_code"
LOGIN_CODE_INVALID = "login_code_invalid"
LOGIN_CODE_EXPIRED = "login_code_expired"
LOGIN_REJECTED = "login_rejected"
LOGIN_PASSWORD_INVALID = "login_password_invalid"
LOGIN_PASSWORD_REJECTED = "login_password_rejected"
LOGIN_PHONE_INVALID = "login_phone_invalid"
USERNAME_INVALID = "username_invalid"
USERNAME_NOT_FOUND = "username_not_found"
NOT_A_PERSON = "not_a_person"
DIALOGS_FAILED = "dialogs_failed"
MESSAGES_FAILED = "messages_failed"
SEND_REJECTED = "send_rejected"
SEND_UNKNOWN = "send_unknown"
SEND_FAILED = "send_failed"
FLOOD_WAIT = "flood_wait"
NOT_AUTHORIZED = "not_authorized"
