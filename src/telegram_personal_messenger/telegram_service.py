"""Сервисный слой Telethon.

Здесь сосредоточены все сетевые вызовы. Наружу отдаются только доменные
модели и безопасные коды ошибок; тексты сообщений, имена и секреты
не логируются.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from telethon import TelegramClient, events, functions, utils
from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession
from telethon.tl.types import (
    DialogFilter,
    DialogFilterChatlist,
    InputMessagesFilterDocument,
    InputMessagesFilterGif,
    InputMessagesFilterMusic,
    InputMessagesFilterPhotoVideo,
    InputMessagesFilterPhotos,
    InputMessagesFilterRoundVideo,
    InputMessagesFilterUrl,
    InputMessagesFilterVideo,
    InputMessagesFilterVoice,
    ReactionEmoji,
    SendMessageCancelAction,
    SendMessageTypingAction,
    User,
)

from . import errors
from .config import Settings
from .errors import TelegramServiceError
from .folders import all_folder, archive_folder
from .formatting import preview
from .models import (
    Account,
    Chat,
    Folder,
    Message,
    MessageValidationError,
    Reaction,
    SendOutcome,
    validate_message,
)

logger = logging.getLogger(__name__)

MessageCallback = Callable[[Message], Any | Awaitable[Any]]

_MESSAGE_FILTERS = {
    "photo": InputMessagesFilterPhotos,
    "video": InputMessagesFilterVideo,
    "photo_video": InputMessagesFilterPhotoVideo,
    "voice": InputMessagesFilterVoice,
    "video_note": InputMessagesFilterRoundVideo,
    "document": InputMessagesFilterDocument,
    "music": InputMessagesFilterMusic,
    "url": InputMessagesFilterUrl,
    "gif": InputMessagesFilterGif,
}


class TelegramService:
    """Обёртка над Telethon, пригодная для вызова из asyncio-воркера."""

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[..., TelegramClient] = TelegramClient,
    ) -> None:
        self._settings = settings
        self._entities: dict[int, Any] = {}
        self._message_cache: dict[tuple[int, int], Any] = {}
        self._me: Account | None = None
        self._listening = False
        self._connect_lock = asyncio.Lock()

        try:
            settings.session_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise TelegramServiceError(errors.CONNECTION) from exc

        session: str | StringSession
        if settings.session_string:
            try:
                session = StringSession(settings.session_string)
            except Exception:
                logger.warning("Строковая сессия повреждена, использую файл сессии")
                session = str(settings.session_path)
        else:
            session = str(settings.session_path)

        proxy = settings.proxy.as_telethon() if settings.proxy is not None else None
        options: dict[str, Any] = {
            "request_retries": 0,
            "connection_retries": 3,
            "retry_delay": 1,
            "flood_sleep_threshold": 0,
            "device_model": "Telegram Personal Messenger",
            "app_version": "0.2.0",
            "proxy": proxy,
        }
        if settings.proxy is not None and settings.proxy.kind == "mtproto":
            from telethon.network.connection import (
                ConnectionTcpMTProxyIntermediate,
                ConnectionTcpMTProxyRandomizedIntermediate,
            )

            secret = settings.proxy.secret or ""
            options["connection"] = (
                ConnectionTcpMTProxyRandomizedIntermediate
                if secret.startswith("dd")
                else ConnectionTcpMTProxyIntermediate
            )

        try:
            self._client = client_factory(
                session,
                settings.api_id,
                settings.api_hash,
                **options,
            )
        except Exception as exc:
            raise TelegramServiceError(errors.CONNECTION) from exc

    # ── Подключение и авторизация ────────────────────────────────────

    async def _ensure_connected(self) -> None:
        async with self._connect_lock:
            try:
                if not self._client.is_connected():
                    await self._client.connect()
            except Exception as exc:
                raise TelegramServiceError(errors.CONNECTION) from exc

    async def is_authorized(self) -> bool:
        await self._ensure_connected()
        try:
            return bool(await self._client.is_user_authorized())
        except Exception as exc:
            raise TelegramServiceError(errors.CONNECTION) from exc

    async def get_me(self) -> Account:
        await self._ensure_connected()
        try:
            me = await self._client.get_me()
        except Exception as exc:
            raise TelegramServiceError(errors.CONNECTION) from exc
        if me is None:
            raise TelegramServiceError(errors.NOT_AUTHORIZED)

        account = Account(
            id=int(getattr(me, "id", 0)),
            display_name=_display_name(me),
            username=getattr(me, "username", None),
        )
        self._me = account
        return account

    async def request_login_code(self, phone: str) -> None:
        normalized = phone.strip()
        if not normalized:
            raise TelegramServiceError(errors.LOGIN_PHONE_INVALID)
        await self._ensure_connected()
        try:
            await self._client.send_code_request(normalized)
        except PhoneNumberInvalidError as exc:
            raise TelegramServiceError(errors.LOGIN_PHONE_INVALID) from exc
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except (RPCError, ValueError) as exc:
            raise TelegramServiceError(errors.LOGIN_SEND_CODE) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.CONNECTION) from exc

    async def sign_in_code(self, phone: str, code: str) -> bool:
        """Возвращает True, если вход завершён, и False, если нужен пароль 2FA."""

        await self._ensure_connected()
        try:
            await self._client.sign_in(phone=phone.strip(), code=code.strip())
        except SessionPasswordNeededError:
            return False
        except PhoneCodeInvalidError as exc:
            raise TelegramServiceError(errors.LOGIN_CODE_INVALID) from exc
        except PhoneCodeExpiredError as exc:
            raise TelegramServiceError(errors.LOGIN_CODE_EXPIRED) from exc
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except RPCError as exc:
            raise TelegramServiceError(errors.LOGIN_REJECTED) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.LOGIN_REJECTED) from exc
        self._me = None
        return True

    async def sign_in_password(self, password: str) -> None:
        await self._ensure_connected()
        try:
            await self._client.sign_in(password=password)
        except PasswordHashInvalidError as exc:
            raise TelegramServiceError(errors.LOGIN_PASSWORD_INVALID) from exc
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except RPCError as exc:
            raise TelegramServiceError(errors.LOGIN_PASSWORD_REJECTED) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.LOGIN_PASSWORD_REJECTED) from exc
        self._me = None

    def session_string(self) -> str:
        session = self._client.session
        if isinstance(session, StringSession):
            return session.save()
        return ""

    # ── Папки и список чатов ────────────────────────────────────────

    async def list_folders(self) -> list[Folder]:
        await self._ensure_connected()
        try:
            result = await self._client(functions.messages.GetDialogFiltersRequest())
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except RPCError as exc:
            logger.warning("Не удалось загрузить папки: %s", type(exc).__name__)
            return [all_folder(), archive_folder()]
        except Exception as exc:
            raise TelegramServiceError(errors.DIALOGS_FAILED) from exc

        raw_filters = getattr(result, "filters", result)
        if not isinstance(raw_filters, (list, tuple)):
            raw_filters = []

        folders = [all_folder(), archive_folder()]
        seen: set[int] = set()
        for raw in raw_filters:
            folder = self._to_folder(raw)
            if folder is None or folder.id in seen:
                continue
            seen.add(folder.id)
            folders.append(folder)
        return folders

    async def list_chats(self) -> list[Chat]:
        await self._ensure_connected()
        try:
            dialogs = await self._client.get_dialogs(limit=None)
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.DIALOGS_FAILED) from exc

        chats: list[Chat] = []
        for dialog in dialogs or []:
            try:
                chat = self._to_chat(dialog)
            except Exception:
                logger.debug("Пропускаю диалог, который не удалось разобрать")
                continue
            if chat is not None:
                chats.append(chat)
        return chats

    async def get_messages(
        self,
        chat_id: int,
        limit: int = 60,
        offset_id: int = 0,
        *,
        filter_type: str | None = None,
    ) -> list[Message]:
        await self._ensure_connected()
        entity = await self._entity(chat_id)
        message_filter = _MESSAGE_FILTERS.get(filter_type) if filter_type else None
        try:
            messages = await self._client.get_messages(
                entity,
                limit=limit,
                offset_id=offset_id,
                filter=message_filter,
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.MESSAGES_FAILED) from exc

        raw_messages = [message for message in (messages or []) if message is not None]
        await self._cache_senders(raw_messages)
        result = [self._to_message(message, chat_id) for message in raw_messages]
        result.reverse()
        return result

    async def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        reply_to: int | None = None,
    ) -> SendOutcome:
        try:
            message_text = validate_message(text)
        except MessageValidationError as exc:
            return SendOutcome("failed", exc.code)

        await self._ensure_connected()
        entity = await self._entity(chat_id)
        try:
            sent = await self._client.send_message(
                entity,
                message_text,
                parse_mode=None,
                reply_to=reply_to,
            )
        except FloodWaitError as exc:
            return SendOutcome(
                "failed",
                errors.FLOOD_WAIT,
                seconds=int(exc.seconds),
            )
        except (asyncio.TimeoutError, TimeoutError, OSError):
            return SendOutcome("unknown", errors.SEND_UNKNOWN)
        except RPCError:
            return SendOutcome("failed", errors.SEND_REJECTED)
        except Exception:
            return SendOutcome("failed", errors.SEND_FAILED)

        if isinstance(sent, list):
            sent = sent[0] if sent else None
        message = self._to_message(sent, chat_id) if sent is not None else None
        return SendOutcome("sent", "sent", sent_message=message)

    async def resolve_username(self, username: str) -> Chat:
        normalized = username.strip()
        if normalized.startswith("@"):
            normalized = normalized[1:]
        if not normalized or "@" in normalized or any(
            char.isspace() for char in normalized
        ):
            raise TelegramServiceError(errors.USERNAME_INVALID)

        await self._ensure_connected()
        try:
            entity = await self._client.get_entity(normalized)
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except (ValueError, RPCError) as exc:
            raise TelegramServiceError(errors.USERNAME_NOT_FOUND) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.USERNAME_NOT_FOUND) from exc

        if not isinstance(entity, User) or getattr(entity, "deleted", False):
            raise TelegramServiceError(errors.NOT_A_PERSON)

        chat_id = utils.get_peer_id(entity)
        self._entities[chat_id] = entity
        return Chat(
            id=chat_id,
            title=_display_name(entity),
            username=getattr(entity, "username", None),
            kind="bot" if getattr(entity, "bot", False) else "user",
            is_contact=bool(getattr(entity, "contact", False)),
        )

    async def mark_read(self, chat_id: int) -> None:
        """Тихо отмечает чат прочитанным; сбой не мешает интерфейсу."""

        try:
            entity = await self._entity(chat_id)
            method = getattr(self._client, "send_read_acknowledge", None)
            if method is not None:
                await method(entity, clear_mentions=True, clear_reactions=True)
        except Exception:
            logger.debug("Не удалось отметить чат прочитанным")

    # ── Действия с сообщениями и чатами ─────────────────────────────

    async def _input_peer(self, chat_id: int) -> Any:
        entity = await self._entity(chat_id)
        return await self._client.get_input_entity(entity)

    async def pin_message(
        self,
        chat_id: int,
        message_id: int,
        *,
        notify: bool = False,
        pm_oneside: bool = False,
    ) -> None:
        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            await self._client.pin_message(
                entity,
                message_id,
                notify=notify,
                pm_oneside=pm_oneside,
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def unpin_message(self, chat_id: int, message_id: int | None = None) -> None:
        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            await self._client.unpin_message(entity, message_id)
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
    ) -> Message | None:
        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            edited = await self._client.edit_message(
                entity,
                message_id,
                text,
                parse_mode=None,
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc
        return self._to_message(edited, chat_id) if edited is not None else None

    async def delete_message(
        self,
        chat_id: int,
        message_id: int,
        *,
        revoke: bool = True,
    ) -> None:
        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            await self._client.delete_messages(entity, message_id, revoke=revoke)
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def send_reaction(
        self,
        chat_id: int,
        message_id: int,
        emoticons: list[str],
        *,
        big: bool = False,
    ) -> None:
        await self._ensure_connected()
        try:
            peer = await self._input_peer(chat_id)
            await self._client(
                functions.messages.SendReactionRequest(
                    peer=peer,
                    msg_id=message_id,
                    big=big,
                    reaction=[ReactionEmoji(emoticon=emoji) for emoji in emoticons],
                )
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def get_draft(self, chat_id: int) -> str | None:
        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            drafts = await self._client.get_drafts(entity)
            if drafts:
                text = drafts[0].text
                if text:
                    return text
        except Exception:
            logger.debug("Не удалось прочитать черновик")
        return None

    async def set_draft(self, chat_id: int, text: str) -> None:
        await self._ensure_connected()
        try:
            peer = await self._input_peer(chat_id)
            await self._client(
                functions.messages.SaveDraftRequest(peer=peer, message=text)
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def set_typing(self, chat_id: int, typing: bool = True) -> None:
        await self._ensure_connected()
        try:
            peer = await self._input_peer(chat_id)
            action = (
                SendMessageTypingAction()
                if typing
                else SendMessageCancelAction()
            )
            await self._client(
                functions.messages.SetTypingRequest(peer=peer, action=action)
            )
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def forward_messages(
        self,
        chat_id: int,
        message_ids: list[int],
        to_chat_id: int,
        *,
        as_album: bool = False,
    ) -> None:
        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            to_entity = await self._entity(to_chat_id)
            await self._client.forward_messages(
                to_entity,
                message_ids,
                from_peer=entity,
                as_album=as_album,
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    async def forward_to_saved(
        self,
        chat_id: int,
        message_ids: list[int],
        *,
        as_album: bool = False,
    ) -> None:
        """Пересылает сообщения в «Избранное» (диалог с самим собой)."""

        await self._ensure_connected()
        try:
            entity = await self._entity(chat_id)
            me = await self._client.get_entity("me")
            await self._client.forward_messages(
                me,
                message_ids,
                from_peer=entity,
                as_album=as_album,
            )
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.ACTION_FAILED) from exc

    # ── Входящие сообщения ──────────────────────────────────────────

    def start_listening(self, callback: MessageCallback) -> None:
        if self._listening:
            return
        self._listening = True

        @self._client.on(events.NewMessage())
        async def _handle(event):  # pragma: no cover - проверяется вручную
            try:
                message = self._to_message(event.message, event.chat_id)
            except Exception:
                logger.debug("Не удалось разобрать входящее сообщение")
                return
            try:
                result = callback(message)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.debug("Обработчик входящего сообщения завершился ошибкой")

        logger.info("Подписка на новые сообщения включена")

    async def disconnect(self) -> None:
        try:
            if self._client.is_connected():
                await self._client.disconnect()
        except Exception:
            logger.debug("Ошибка при отключении клиента")

    # ── Преобразование Telethon → доменные модели ──────────────────

    def _to_folder(self, raw: Any) -> Folder | None:
        if not isinstance(raw, (DialogFilter, DialogFilterChatlist)):
            return None
        folder_id = getattr(raw, "id", None)
        if folder_id is None:
            return None

        title = _text_value(getattr(raw, "title", "")) or f"Папка {folder_id}"
        return Folder(
            key=f"folder:{folder_id}",
            title=title,
            kind="custom",
            id=int(folder_id),
            pinned_peers=_peer_ids(getattr(raw, "pinned_peers", [])),
            include_peers=_peer_ids(getattr(raw, "include_peers", [])),
            exclude_peers=_peer_ids(getattr(raw, "exclude_peers", [])),
            contacts=bool(getattr(raw, "contacts", False)),
            non_contacts=bool(getattr(raw, "non_contacts", False)),
            groups=bool(getattr(raw, "groups", False)),
            broadcasts=bool(getattr(raw, "broadcasts", False)),
            bots=bool(getattr(raw, "bots", False)),
            exclude_muted=bool(getattr(raw, "exclude_muted", False)),
            exclude_read=bool(getattr(raw, "exclude_read", False)),
            exclude_archived=bool(getattr(raw, "exclude_archived", False)),
            emoticon=getattr(raw, "emoticon", None),
        )

    def _to_chat(self, dialog: Any) -> Chat | None:
        entity = getattr(dialog, "entity", None)
        if entity is None or getattr(entity, "deleted", False):
            return None

        chat_id = int(getattr(dialog, "id", 0))
        if not chat_id:
            return None
        self._entities[chat_id] = entity

        if getattr(dialog, "is_user", False):
            kind = "bot" if getattr(entity, "bot", False) else "user"
        elif getattr(dialog, "is_group", False):
            kind = "group"
        else:
            kind = "channel"

        last = getattr(dialog, "message", None)
        last_text = self._message_preview(last) if last is not None else ""
        last_out = bool(getattr(last, "out", False)) if last is not None else False
        timestamp = getattr(dialog, "date", None) or getattr(last, "date", None)

        return Chat(
            id=chat_id,
            title=_display_name(entity) or str(chat_id),
            username=getattr(entity, "username", None),
            kind=kind,
            last_message=last_text,
            last_out=last_out,
            date=timestamp,
            unread=int(getattr(dialog, "unread_count", 0) or 0),
            pinned=bool(getattr(dialog, "pinned", False)),
            archived=bool(getattr(dialog, "archived", False)),
            muted=_is_muted(dialog),
            is_contact=bool(getattr(entity, "contact", False)) and kind == "user",
            photo_available=bool(getattr(entity, "photo", None)),
            participants_count=getattr(entity, "participants_count", None),
            is_forum=bool(getattr(entity, "forum", False)),
        )

    def _to_message(self, message: Any, chat_id: int | None = None) -> Message:
        message_chat_id = chat_id
        if message_chat_id is None:
            message_chat_id = getattr(message, "chat_id", 0)
        message_chat_id = int(message_chat_id or 0)

        text = getattr(message, "message", None)
        if text is None:
            text = getattr(message, "text", None) or ""

        out = bool(getattr(message, "out", False))
        sender_name = ""
        if not out:
            sender = getattr(message, "sender", None)
            if sender is not None:
                sender_name = _display_name(sender)
            else:
                sender_id = getattr(message, "sender_id", None)
                cached = self._entities.get(int(sender_id)) if sender_id else None
                if cached is not None:
                    sender_name = _display_name(cached)

        date = getattr(message, "date", None)
        if date is None:
            date = datetime.now(timezone.utc)

        message_id = int(getattr(message, "id", 0) or 0)
        self._cache_raw_message(message_chat_id, message_id, message)

        return Message(
            id=message_id,
            chat_id=message_chat_id,
            text=str(text),
            date=date,
            out=out,
            sender_name=sender_name,
            media=self._media_label(message),
            media_kind=self._media_kind(message),
            reply_to=getattr(message, "reply_to_msg_id", None),
            forwarded_from=_forwarded_from(message),
            pinned=bool(getattr(message, "pinned", False)),
            edited=getattr(message, "edit_date", None) is not None,
            views=getattr(message, "views", None),
            grouped_id=getattr(message, "grouped_id", None),
            reactions=_reactions(message),
        )

    def _cache_raw_message(self, chat_id: int, message_id: int, message: Any) -> None:
        if not message_id:
            return
        if len(self._message_cache) >= 2000:
            self._message_cache.pop(next(iter(self._message_cache)), None)
        self._message_cache[(chat_id, message_id)] = message

    async def _cache_senders(self, messages: list[Any]) -> None:
        """Одним запросом подтягивает имена авторов для групповых сообщений."""

        missing: set[int] = set()
        for message in messages:
            sender_id = getattr(message, "sender_id", None)
            if (
                sender_id
                and getattr(message, "sender", None) is None
                and not getattr(message, "out", False)
            ):
                missing.add(int(sender_id))
        missing -= set(self._entities)
        if not missing:
            return
        try:
            entities = await self._client.get_entity(list(missing))
        except Exception:
            return
        if not isinstance(entities, (list, tuple)):
            entities = [entities]
        for entity in entities:
            entity_id = getattr(entity, "id", None)
            if entity_id is not None:
                self._entities[int(entity_id)] = entity

    def _message_preview(self, message: Any) -> str:
        text = " ".join((getattr(message, "message", None) or "").split())
        media = self._media_label(message)
        if media:
            text = f"{media} · {text}" if text else media
        return preview(text, limit=80)

    def _media_label(self, message: Any) -> str | None:
        if getattr(message, "sticker", None):
            return "Стикер"
        if getattr(message, "photo", None):
            return "Фото"
        if getattr(message, "video_note", None):
            return "Кружок"
        if getattr(message, "voice", None):
            return "Голосовое"
        if getattr(message, "video", None):
            return "Видео"
        if getattr(message, "gif", None):
            return "GIF"
        if getattr(message, "audio", None):
            return "Аудио"
        if getattr(message, "document", None):
            file_info = getattr(message, "file", None)
            name = getattr(file_info, "name", None) if file_info else None
            return f"Файл: {preview(name, 24)}" if name else "Файл"
        if getattr(message, "geo", None):
            return "Геолокация"
        if getattr(message, "contact", None):
            return "Контакт"
        if getattr(message, "poll", None):
            return "Опрос"
        if getattr(message, "dice", None):
            return "Кубик"
        if getattr(message, "web_preview", None):
            return "Ссылка"
        return None

    def _media_kind(self, message: Any) -> str | None:
        if getattr(message, "sticker", None):
            return "sticker"
        if getattr(message, "photo", None):
            return "photo"
        if getattr(message, "video_note", None):
            return "video_note"
        if getattr(message, "voice", None):
            return "voice"
        if getattr(message, "video", None):
            return "video"
        if getattr(message, "gif", None):
            return "gif"
        if getattr(message, "audio", None):
            return "audio"
        if getattr(message, "document", None):
            return "document"
        if getattr(message, "geo", None):
            return "geo"
        if getattr(message, "contact", None):
            return "contact"
        if getattr(message, "poll", None):
            return "poll"
        if getattr(message, "dice", None):
            return "dice"
        if getattr(message, "web_preview", None):
            return "webpage"
        return None

    async def _entity(self, chat_id: int) -> Any:
        entity = self._entities.get(chat_id)
        if entity is not None:
            return entity
        try:
            entity = await self._client.get_entity(chat_id)
        except FloodWaitError as exc:
            raise TelegramServiceError(errors.FLOOD_WAIT, seconds=int(exc.seconds)) from exc
        except Exception as exc:
            raise TelegramServiceError(errors.MESSAGES_FAILED) from exc
        self._entities[chat_id] = entity
        return entity

    async def download_media(
        self,
        chat_id: int,
        message_id: int,
        *,
        thumb: int | None = None,
        file: Any = None,
    ) -> Any:
        """Скачивает медиа сообщения на диск (или в память, если ``file`` нет).

        Возвращает путь или bytes; при ошибке — ``None``.
        """

        message = self._message_cache.get((chat_id, message_id))
        if message is None:
            try:
                entity = await self._entity(chat_id)
                fetched = await self._client.get_messages(entity, ids=message_id)
            except Exception:
                return None
            message = fetched[0] if fetched else None
        if message is None:
            return None
        try:
            return await self._client.download_media(message, file=file, thumb=thumb)
        except Exception:
            return None

    async def download_avatar(self, chat_id: int, file: Any = None) -> Any:
        """Скачивает аватар чата; при отсутствии/ошибке возвращает ``None``."""

        try:
            entity = await self._entity(chat_id)
            return await self._client.download_profile_photo(
                entity,
                file=file,
                download_big=False,
            )
        except Exception:
            return None


def _display_name(entity: Any) -> str:
    first = getattr(entity, "first_name", None) or ""
    last = getattr(entity, "last_name", None) or ""
    full = " ".join(part for part in (first, last) if part).strip()
    if full:
        return full
    title = getattr(entity, "title", None)
    if title:
        return str(title)
    username = getattr(entity, "username", None)
    if username:
        return str(username)
    entity_id = getattr(entity, "id", "")
    return str(entity_id) if entity_id else "Без имени"


def _reactions(message: Any) -> tuple[Reaction, ...]:
    raw = getattr(message, "reactions", None)
    results = getattr(raw, "results", None) or []
    reactions: list[Reaction] = []
    for item in results:
        emoji = getattr(item, "reaction", None)
        if emoji is None:
            continue
        if isinstance(emoji, str):
            emoticon = emoji
        else:
            emoticon = getattr(emoji, "emoticon", None)
            if not emoticon:
                document_id = getattr(emoji, "document_id", None)
                emoticon = str(document_id) if document_id is not None else None
        if not emoticon:
            continue
        reactions.append(
            Reaction(
                emoticon=str(emoticon),
                count=int(getattr(item, "count", 0) or 0),
                chosen=getattr(item, "chosen_order", None) is not None,
            )
        )
    return tuple(reactions)


def _forwarded_from(message: Any) -> str | None:
    forward = getattr(message, "forward", None)
    if forward is None:
        return None
    sender = getattr(forward, "sender", None)
    if sender is not None:
        return _display_name(sender)
    chat = getattr(forward, "chat", None)
    if chat is not None:
        return _display_name(chat)
    original = getattr(forward, "original_fwd", None)
    if original is not None:
        return (
            getattr(original, "from_name", None)
            or getattr(original, "post_author", None)
            or None
        )
    return None


def _text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    text = getattr(value, "text", None)
    return str(text) if text is not None else str(value)


def _peer_ids(peers: Any) -> frozenset[int]:
    result: set[int] = set()
    for peer in peers or []:
        try:
            result.add(int(utils.get_peer_id(peer)))
            continue
        except Exception:
            pass
        for attribute in ("user_id", "chat_id", "channel_id"):
            value = getattr(peer, attribute, None)
            if value:
                result.add(int(value))
                break
    return frozenset(result)


def _is_muted(dialog: Any) -> bool:
    raw = getattr(dialog, "dialog", None)
    notify = getattr(raw, "notify_settings", None)
    until = getattr(notify, "mute_until", None)
    if not until:
        return False
    if isinstance(until, datetime):
        now = datetime.now(timezone.utc)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return until > now
    return True
