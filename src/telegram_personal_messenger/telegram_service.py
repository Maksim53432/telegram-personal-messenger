import asyncio
from typing import Callable, Literal

from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.tl.types import User

from .config import Settings
from .models import Recipient, SendOutcome, validate_message


class TelegramServiceError(Exception):
    """An operation failed with a user-safe message."""


class TelegramService:
    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., TelegramClient] = TelegramClient,
        user_type: type = User,
    ) -> None:
        self._client = client_factory(
            str(settings.session_path),
            settings.api_id,
            settings.api_hash,
            request_retries=0,
            flood_sleep_threshold=0,
        )
        self._user_type = user_type
        self._entities: dict[int, User] = {}

    async def _ensure_connected(self) -> None:
        if not self._client.is_connected():
            await self._client.connect()

    async def is_authorized(self) -> bool:
        await self._ensure_connected()
        return await self._client.is_user_authorized()

    async def disconnect(self) -> None:
        if self._client.is_connected():
            await self._client.disconnect()

    async def request_login_code(self, phone: str) -> None:
        await self._ensure_connected()
        try:
            await self._client.send_code_request(phone)
        except RPCError as exc:
            raise TelegramServiceError(
                "Telegram could not send a login code. Check the phone number and try again."
            ) from exc

    async def sign_in_code(
        self,
        phone: str,
        code: str,
    ) -> Literal["authenticated", "password_required"]:
        await self._ensure_connected()
        try:
            await self._client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            return "password_required"
        except PhoneCodeInvalidError as exc:
            raise TelegramServiceError("The Telegram login code was not accepted.") from exc
        except PhoneCodeExpiredError as exc:
            raise TelegramServiceError("The Telegram login code expired. Request a new code.") from exc
        except RPCError as exc:
            raise TelegramServiceError("Telegram rejected the login request.") from exc
        return "authenticated"

    async def sign_in_password(self, password: str) -> None:
        await self._ensure_connected()
        try:
            await self._client.sign_in(password=password)
        except PasswordHashInvalidError as exc:
            raise TelegramServiceError("The two-step verification password was not accepted.") from exc
        except RPCError as exc:
            raise TelegramServiceError("Telegram rejected the two-step verification password.") from exc

    async def list_recipients(self) -> list[Recipient]:
        await self._ensure_connected()
        recipients = []
        for dialog in await self._client.get_dialogs():
            entity = dialog.entity
            if isinstance(entity, self._user_type):
                recipient = self._to_recipient(entity)
                self._entities[recipient.id] = entity
                recipients.append(recipient)
        return recipients

    async def resolve_username(self, username: str) -> Recipient:
        normalized = username.strip()
        if normalized.startswith("@"):
            normalized = normalized[1:]
        if not normalized or "@" in normalized or any(char.isspace() for char in normalized):
            raise TelegramServiceError("Enter one complete Telegram @username.")

        await self._ensure_connected()
        try:
            entity = await self._client.get_entity(normalized)
        except (ValueError, RPCError) as exc:
            raise TelegramServiceError("That Telegram username could not be resolved.") from exc

        if not isinstance(entity, self._user_type):
            raise TelegramServiceError("Choose a personal Telegram account, not a group or channel.")

        recipient = self._to_recipient(entity)
        self._entities[recipient.id] = entity
        return recipient

    async def send_message(self, recipient: Recipient, text: str) -> SendOutcome:
        try:
            validate_message(text)
        except ValueError as exc:
            return SendOutcome("failed", str(exc))

        entity = self._entities.get(recipient.id)
        if entity is None or not isinstance(entity, self._user_type):
            return SendOutcome("failed", "Select a person from the chat list or username search.")

        try:
            await self._ensure_connected()
        except Exception:
            return SendOutcome("failed", "Could not connect to Telegram. Check your connection.")

        try:
            await self._client.send_message(entity, text, parse_mode=None)
        except (asyncio.TimeoutError, TimeoutError, OSError) as exc:
            return SendOutcome(
                "unknown",
                "Delivery result is unknown. The message may have been sent; the app did not retry.",
            )
        except RPCError as exc:
            return SendOutcome("failed", "Telegram rejected the message. Check the recipient and try again.")
        except Exception as exc:
            return SendOutcome("failed", "Could not send the message. Check the connection and try again.")
        return SendOutcome("sent", "Message sent.")

    def _to_recipient(self, entity: User) -> Recipient:
        first_name = getattr(entity, "first_name", "") or ""
        last_name = getattr(entity, "last_name", "") or ""
        display_name = " ".join(part for part in (first_name, last_name) if part).strip()
        if not display_name:
            display_name = getattr(entity, "username", None) or str(entity.id)
        return Recipient(
            id=entity.id,
            display_name=display_name,
            username=getattr(entity, "username", None),
        )
