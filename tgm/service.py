"""Telegram account access for the UI.

Runs on the Qt thread: qasync drives asyncio from the Qt event loop, so
signals are emitted directly and slots may start coroutines with `spawn`.
All ids travel as `object` because Qt's `int` is 32-bit.
"""

from __future__ import annotations

import asyncio
import glob
import logging
import os
import platform
import time
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from telethon import TelegramClient, events, functions, utils
from telethon.errors import SessionPasswordNeededError
from telethon.tl import types as t

from . import __version__
from .config import Settings
from .folders import Folder, folder_from_filter
from .models import (
    ChatItem,
    MessageItem,
    ReplyInfo,
    chat_from_dialog,
    chat_from_entity,
    display_name,
    message_from_telethon,
    mute_until,
    pick_photo_size,
)
from .session import open_session

log = logging.getLogger(__name__)

TYPING_TTL = 6.0


class PasswordNeeded(Exception):
    """Sign-in requires the two-step verification password."""


class TelegramService(QObject):
    state_changed = Signal(str)  # connecting | online | offline
    auth_required = Signal()
    authorized = Signal(object)  # ChatItem of the account itself
    chats_added = Signal(list)  # list[ChatItem]
    chats_loaded = Signal()  # initial dialog load finished
    chat_changed = Signal(object)  # ChatItem
    folders_changed = Signal(list)  # list[Folder]
    message_new = Signal(object)  # MessageItem
    message_edited = Signal(object)  # MessageItem
    messages_deleted = Signal(object, list)  # chat_id | None, [ids]
    outbox_read = Signal(object, object)  # chat_id, max_id
    typing_changed = Signal(object)  # chat_id
    status_changed = Signal(object)  # user peer id

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.chats: dict[int, ChatItem] = {}
        self.folders: list[Folder] = []
        self.me: ChatItem | None = None
        self._peers: dict[int, object] = {}  # any entity seen, for avatars of senders
        self._raw: OrderedDict[tuple[int, int], object] = OrderedDict()
        self._typing: dict[int, dict[int, tuple[str, float]]] = {}
        self._inflight: dict[str, asyncio.Future] = {}
        self._download_slots = asyncio.Semaphore(4)
        self._last_typing_sent: dict[int, float] = {}
        self._state = ""
        self._phone = ""
        self._phone_hash = ""

        for sub in ("avatars", "thumbs", "files"):
            (settings.cache_dir / sub).mkdir(parents=True, exist_ok=True)
        self.downloads_dir = settings.data_dir / "downloads"
        self.downloads_dir.mkdir(parents=True, exist_ok=True)

        proxy = settings.proxy.telethon_kwargs() if settings.proxy else {}
        self.client = TelegramClient(
            open_session(settings.session_file, settings.session_string),
            settings.api_id,
            settings.api_hash,
            device_model="tg-messenger-claude",
            system_version=f"{platform.system()} {platform.release()}",
            app_version=__version__,
            lang_code="ru",
            system_lang_code="ru",
            connection_retries=None,
            retry_delay=3,
            auto_reconnect=True,
            **proxy,
        )
        c = self.client
        c.add_event_handler(self._on_new_message, events.NewMessage())
        c.add_event_handler(self._on_edited, events.MessageEdited())
        c.add_event_handler(self._on_deleted, events.MessageDeleted())
        c.add_event_handler(self._on_read, events.MessageRead(inbox=False))
        c.add_event_handler(self._on_read, events.MessageRead(inbox=True))
        c.add_event_handler(self._on_user_update, events.UserUpdate())
        c.add_event_handler(self._on_raw, events.Raw())

        self._state_timer = QTimer(self, interval=2000, timeout=self._poll_state)
        self._typing_timer = QTimer(self, interval=1000, timeout=self._expire_typing)

    # --- connection & auth -------------------------------------------------

    async def start(self) -> None:
        self._set_state("connecting")
        await self.client.connect()
        self._state_timer.start()
        self._poll_state()
        if await self.client.is_user_authorized():
            await self._after_login()
        else:
            self.auth_required.emit()

    async def stop(self) -> None:
        self._state_timer.stop()
        self._typing_timer.stop()
        await self.client.disconnect()

    def _poll_state(self) -> None:
        self._set_state("online" if self.client.is_connected() else "connecting")

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    async def send_code(self, phone: str) -> None:
        self._phone = phone
        sent = await self.client.send_code_request(phone)
        self._phone_hash = sent.phone_code_hash

    async def sign_in_code(self, code: str) -> None:
        try:
            await self.client.sign_in(self._phone, code, phone_code_hash=self._phone_hash)
        except SessionPasswordNeededError:
            raise PasswordNeeded from None
        await self._after_login()

    async def sign_in_password(self, password: str) -> None:
        await self.client.sign_in(password=password)
        await self._after_login()

    async def _after_login(self) -> None:
        me = await self.client.get_me()
        self.me = chat_from_entity(me)
        self._peers[self.me.peer_id] = me
        self._typing_timer.start()
        self.authorized.emit(self.me)
        await asyncio.gather(self.load_folders(), self.load_dialogs())
        try:
            await self.client.catch_up()
        except Exception:
            log.exception("catch_up failed")

    # --- dialogs & folders -------------------------------------------------

    async def load_dialogs(self) -> None:
        batch: list[ChatItem] = []
        rank = 0
        async for dialog in self.client.iter_dialogs():
            try:
                chat = chat_from_dialog(dialog, rank)
            except Exception:
                log.exception("skipping dialog %s", dialog.id)
                continue
            rank += 1
            self._peers[chat.peer_id] = dialog.entity
            if dialog.message is not None:
                self._remember(dialog.message)
            self.chats[chat.peer_id] = chat
            batch.append(chat)
            if len(batch) >= 100:
                self.chats_added.emit(batch)
                batch = []
        if batch:
            self.chats_added.emit(batch)
        self.chats_loaded.emit()

    async def load_folders(self) -> None:
        result = await self.client(functions.messages.GetDialogFiltersRequest())
        filters = getattr(result, "filters", result)
        self.folders = [f for f in map(folder_from_filter, filters) if f is not None]
        self.folders_changed.emit(self.folders)

    async def refresh_dialog(self, chat: ChatItem) -> None:
        """Re-read unread counters and top message of one dialog from the server."""
        peer = await self.client.get_input_entity(chat.peer_id)
        res = await self.client(functions.messages.GetPeerDialogsRequest([t.InputDialogPeer(peer)]))
        for d in res.dialogs:
            chat.unread = d.unread_count
            chat.mentions = d.unread_mentions_count
            chat.read_inbox_max_id = d.read_inbox_max_id
            chat.read_outbox_max_id = d.read_outbox_max_id
            chat.unread_mark = bool(d.unread_mark)
        msgs = await self.client.get_messages(peer, limit=1)
        chat.last = message_from_telethon(msgs[0]) if msgs else None
        self.chat_changed.emit(chat)

    def chat(self, peer_id: int) -> ChatItem | None:
        return self.chats.get(peer_id)

    async def resolve_username(self, username: str) -> ChatItem:
        entity = await self.client.get_entity(username)
        return self._chat_for_entity(entity)

    async def resolve_peer(self, peer_id: int) -> ChatItem:
        if peer_id in self.chats:
            return self.chats[peer_id]
        entity = self._peers.get(peer_id) or await self.client.get_entity(peer_id)
        return self._chat_for_entity(entity)

    def _chat_for_entity(self, entity) -> ChatItem:
        peer_id = utils.get_peer_id(entity)
        self._peers[peer_id] = entity
        if peer_id in self.chats:
            return self.chats[peer_id]
        chat = chat_from_entity(entity)
        chat.in_dialogs = False
        return chat

    async def search_global(self, query: str) -> list[ChatItem]:
        res = await self.client(functions.contacts.SearchRequest(q=query, limit=20))
        return [self._chat_for_entity(e) for e in [*res.users, *res.chats]]

    async def describe(self, chat: ChatItem) -> str:
        """Second line of the chat header: presence or member count."""
        entity = chat.entity
        if chat.kind == "self":
            return ""
        if chat.kind == "bot":
            return "бот"
        if isinstance(entity, t.User):
            return presence_text(entity.status)
        count = getattr(entity, "participants_count", None)
        if count is None and isinstance(entity, t.Channel):
            full = await self.client(functions.channels.GetFullChannelRequest(entity))
            count = full.full_chat.participants_count
            entity.participants_count = count
        if count is None:
            return ""
        noun = ("подписчик", "подписчика", "подписчиков") if chat.kind == "channel" else (
            "участник", "участника", "участников")
        return f"{count} {plural(count, *noun)}"

    # --- messages ----------------------------------------------------------

    def _remember(self, msg) -> None:
        key = (utils.get_peer_id(msg.peer_id), msg.id)
        self._raw[key] = msg
        self._raw.move_to_end(key)
        while len(self._raw) > 5000:
            self._raw.popitem(last=False)
        for entity in (msg.sender, getattr(msg, "chat", None)):
            if entity is not None:
                self._peers[utils.get_peer_id(entity)] = entity

    async def _raw_message(self, chat_id: int, msg_id: int):
        msg = self._raw.get((chat_id, msg_id))
        if msg is None:
            msg = await self.client.get_messages(chat_id, ids=msg_id)
            if msg is None:
                raise LookupError("Сообщение не найдено")
            self._remember(msg)
        return msg

    async def history(self, chat: ChatItem, offset_id: int = 0, limit: int = 50) -> list[MessageItem]:
        """Messages older than `offset_id` (0 = newest), oldest first."""
        msgs = await self.client.get_messages(chat.entity or chat.peer_id, limit=limit, offset_id=offset_id)
        for m in msgs:
            self._remember(m)
        items = [message_from_telethon(m) for m in reversed(msgs)]
        await self._fill_replies(chat, items)
        return items

    async def _fill_replies(self, chat: ChatItem, items: list[MessageItem]) -> None:
        wanted = [i.reply.msg_id for i in items if i.reply and (chat.peer_id, i.reply.msg_id) not in self._raw]
        if wanted:
            try:
                fetched = await self.client.get_messages(chat.entity or chat.peer_id, ids=list(set(wanted)))
                for m in fetched:
                    if m is not None:
                        self._remember(m)
            except Exception:
                log.exception("reply lookup failed")
        for item in items:
            if item.reply:
                fill_reply(item.reply, self._raw.get((chat.peer_id, item.reply.msg_id)))

    async def send_text(self, chat: ChatItem, text: str, reply_to: int | None = None) -> MessageItem:
        msg = await self.client.send_message(chat.entity or chat.peer_id, text, reply_to=reply_to)
        return await self._sent(chat, msg)

    async def send_file(self, chat: ChatItem, path: str, caption: str = "", reply_to: int | None = None,
                        as_document: bool = False, progress=None) -> MessageItem:
        msg = await self.client.send_file(
            chat.entity or chat.peer_id, path, caption=caption, reply_to=reply_to,
            force_document=as_document, progress_callback=progress,
        )
        return await self._sent(chat, msg)

    async def _sent(self, chat: ChatItem, msg) -> MessageItem:
        self._remember(msg)
        item = message_from_telethon(msg)
        await self._fill_replies(chat, [item])
        self._apply_new(chat, item)
        return item

    async def edit(self, chat: ChatItem, msg_id: int, text: str) -> MessageItem:
        msg = await self.client.edit_message(chat.entity or chat.peer_id, msg_id, text)
        self._remember(msg)
        item = message_from_telethon(msg)
        await self._fill_replies(chat, [item])
        if chat.last and chat.last.id == item.id:
            chat.last = item
            self.chat_changed.emit(chat)
        self.message_edited.emit(item)
        return item

    async def delete(self, chat: ChatItem, ids: list[int], revoke: bool) -> None:
        await self.client.delete_messages(chat.entity or chat.peer_id, ids, revoke=revoke)
        self.messages_deleted.emit(chat.peer_id, ids)
        if chat.last and chat.last.id in ids:
            await self.refresh_dialog(chat)

    async def forward(self, source: ChatItem, ids: list[int], target: ChatItem) -> None:
        msgs = await self.client.forward_messages(target.entity or target.peer_id, ids, source.entity or source.peer_id)
        for msg in msgs if isinstance(msgs, list) else [msgs]:
            if msg is not None:
                await self._sent(target, msg)

    async def mark_read(self, chat: ChatItem, max_id: int) -> None:
        if max_id <= chat.read_inbox_max_id and not (chat.unread or chat.unread_mark or chat.mentions):
            return
        chat.read_inbox_max_id = max(max_id, chat.read_inbox_max_id)
        chat.unread = chat.mentions = 0
        chat.unread_mark = False
        self.chat_changed.emit(chat)
        await self.client.send_read_acknowledge(chat.entity or chat.peer_id, max_id=max_id, clear_mentions=True)

    async def send_typing(self, chat: ChatItem) -> None:
        now = time.monotonic()
        if now - self._last_typing_sent.get(chat.peer_id, 0) < 5:
            return
        self._last_typing_sent[chat.peer_id] = now
        peer = await self.client.get_input_entity(chat.entity or chat.peer_id)
        await self.client(functions.messages.SetTypingRequest(peer, t.SendMessageTypingAction()))

    def typing_text(self, chat_id: int) -> str:
        people = self._typing.get(chat_id)
        if not people:
            return ""
        actions = [a for a, _ in people.values()]
        chat = self.chats.get(chat_id)
        if chat and chat.kind in ("user", "bot"):
            return actions[0]
        names = [display_name(self._peers.get(uid)).split()[0] for uid in people]
        if len(names) == 1:
            return f"{names[0]} {actions[0]}"
        return f"{len(names)} печатают…"

    # --- media -------------------------------------------------------------

    async def _once(self, key: str, factory):
        """Run one download per key; concurrent callers share the result."""
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut = asyncio.ensure_future(self._guarded(factory))
        self._inflight[key] = fut
        try:
            return await asyncio.shield(fut)
        finally:
            self._inflight.pop(key, None)

    async def _guarded(self, factory):
        async with self._download_slots:
            return await factory()

    async def avatar(self, peer_id: int) -> Path | None:
        entity = self._peers.get(peer_id) or getattr(self.chats.get(peer_id), "entity", None)
        photo_id = getattr(getattr(entity, "photo", None), "photo_id", None)
        if not photo_id:
            return None
        path = self.settings.cache_dir / "avatars" / f"{peer_id}_{photo_id}.jpg"
        if path.exists():
            return path

        async def fetch():
            data = await self.client.download_profile_photo(entity, file=bytes, download_big=False)
            return write_atomic(path, data) if data else None

        return await self._once(str(path), fetch)

    async def thumbnail(self, item: MessageItem) -> Path | None:
        """Preview image for photos, videos, stickers and documents with thumbs."""
        media = item.media
        if media is None:
            return None
        ext = ".webp" if media.kind == "sticker" and media.mime == "image/webp" else ".jpg"
        path = self.settings.cache_dir / "thumbs" / f"{item.chat_id}_{item.id}{ext}"
        if path.exists():
            return path

        async def fetch():
            msg = await self._raw_message(item.chat_id, item.id)
            if media.kind == "photo":
                size = pick_photo_size(msg.media.photo.sizes)
                data = await self.client.download_media(msg, file=bytes, thumb=size.type if size else None)
            elif ext == ".webp":
                data = await self.client.download_media(msg, file=bytes)
            elif media.has_thumb:
                data = await self.client.download_media(msg, file=bytes, thumb=-1)
            else:
                return None
            return write_atomic(path, data) if data else None

        return await self._once(str(path), fetch)

    async def download(self, item: MessageItem, progress=None) -> Path:
        """Full file: photos into the cache, everything else into data/downloads."""
        media = item.media
        if media and media.kind == "photo":
            folder, name = self.settings.cache_dir / "files", f"{item.chat_id}_{item.id}"
        else:
            safe = "".join(ch for ch in (media.file_name if media else "") if ch not in '/\\\0').strip(". ")
            folder = self.downloads_dir
            name = f"{item.chat_id}_{item.id}_{safe}" if safe else f"{item.chat_id}_{item.id}"
        done = [p for p in folder.glob(glob.escape(name) + "*") if p.is_file()]
        if done:
            return done[0]

        async def fetch():
            msg = await self._raw_message(item.chat_id, item.id)
            partial = self.settings.cache_dir / "partial"
            partial.mkdir(exist_ok=True)
            # Telethon adds the extension; download aside so a cut-off file is never mistaken for a finished one.
            got = await self.client.download_media(msg, file=str(partial / name), progress_callback=progress)
            if not got:
                raise LookupError("Файл недоступен")
            final = folder / Path(got).name
            Path(got).replace(final)
            return final

        return await self._once(f"file:{item.chat_id}:{item.id}", fetch)

    # --- updates -----------------------------------------------------------

    async def _ensure_chat(self, event) -> ChatItem:
        chat = self.chats.get(event.chat_id)
        if chat is None:
            entity = await event.get_chat()
            chat = chat_from_entity(entity)
            self._peers[chat.peer_id] = entity
            self.chats[chat.peer_id] = chat
            self.chats_added.emit([chat])
        elif not chat.in_dialogs:
            chat.in_dialogs = True
            self.chats_added.emit([chat])
        return chat

    def _apply_new(self, chat: ChatItem, item: MessageItem) -> None:
        if chat.peer_id not in self.chats:
            chat.in_dialogs = True
            self.chats[chat.peer_id] = chat
            self.chats_added.emit([chat])
        if chat.last is None or item.id >= chat.last.id:
            chat.last = item
        if item.out:
            chat.unread = 0
        self.message_new.emit(item)
        self.chat_changed.emit(chat)

    async def _on_new_message(self, event) -> None:
        msg = event.message
        try:
            await event.get_sender()
        except Exception:
            pass
        chat = await self._ensure_chat(event)
        if (chat.peer_id, msg.id) in self._raw and chat.last and chat.last.id >= msg.id:
            return  # our own send, already applied
        self._remember(msg)
        item = message_from_telethon(msg)
        await self._fill_replies(chat, [item])
        if not item.out and not item.service and msg.id > chat.read_inbox_max_id:
            chat.unread += 1
            if msg.mentioned:
                chat.mentions += 1
        people = self._typing.get(chat.peer_id)
        if people and people.pop(msg.sender_id, None):
            self.typing_changed.emit(chat.peer_id)
        self._apply_new(chat, item)

    async def _on_edited(self, event) -> None:
        msg = event.message
        self._remember(msg)
        item = message_from_telethon(msg)
        chat = self.chats.get(event.chat_id)
        if chat:
            await self._fill_replies(chat, [item])
            if chat.last and chat.last.id == item.id:
                chat.last = item
                self.chat_changed.emit(chat)
        self.message_edited.emit(item)

    async def _on_deleted(self, event) -> None:
        ids = list(event.deleted_ids)
        self.messages_deleted.emit(event.chat_id, ids)
        if event.chat_id is not None:
            affected = [self.chats.get(event.chat_id)]
        else:  # private chats and small groups share one id space
            affected = [c for c in self.chats.values() if not isinstance(c.entity, t.Channel)]
        for chat in affected:
            if chat and chat.last and chat.last.id in ids:
                await self.refresh_dialog(chat)

    async def _on_read(self, event) -> None:
        chat = self.chats.get(event.chat_id)
        if chat is None:
            return
        if event.outbox:
            chat.read_outbox_max_id = max(chat.read_outbox_max_id, event.max_id)
            self.outbox_read.emit(chat.peer_id, event.max_id)
            self.chat_changed.emit(chat)
            return
        chat.read_inbox_max_id = max(chat.read_inbox_max_id, event.max_id)
        if chat.last is None or event.max_id >= chat.last.id:
            chat.unread = chat.mentions = 0
            chat.unread_mark = False
            self.chat_changed.emit(chat)
        else:
            await self.refresh_dialog(chat)

    async def _on_user_update(self, event) -> None:
        if event.status is not None:
            entity = self._peers.get(event.sender_id)
            if isinstance(entity, t.User):
                entity.status = event.status
            self.status_changed.emit(event.sender_id)
            return
        if event.action is None:
            return
        chat_id = event.chat_id
        if event.sender is not None:
            self._peers.setdefault(event.sender_id, event.sender)
        people = self._typing.setdefault(chat_id, {})
        if event.cancel:
            people.pop(event.sender_id, None)
        else:
            people[event.sender_id] = (action_text(event), time.monotonic() + TYPING_TTL)
        self.typing_changed.emit(chat_id)

    def _expire_typing(self) -> None:
        now = time.monotonic()
        for chat_id, people in list(self._typing.items()):
            stale = [uid for uid, (_, until) in people.items() if until < now]
            for uid in stale:
                del people[uid]
            if stale:
                self.typing_changed.emit(chat_id)

    async def _on_raw(self, update) -> None:
        if isinstance(update, t.UpdateFolderPeers):
            for fp in update.folder_peers:
                chat = self.chats.get(utils.get_peer_id(fp.peer))
                if chat:
                    chat.archived = fp.folder_id == 1
                    self.chat_changed.emit(chat)
        elif isinstance(update, t.UpdateNotifySettings) and isinstance(update.peer, t.NotifyPeer):
            chat = self.chats.get(utils.get_peer_id(update.peer.peer))
            if chat:
                chat.muted_until = mute_until(update.notify_settings)
                self.chat_changed.emit(chat)
        elif isinstance(update, t.UpdateDialogUnreadMark) and isinstance(update.peer, t.DialogPeer):
            chat = self.chats.get(utils.get_peer_id(update.peer.peer))
            if chat:
                chat.unread_mark = bool(update.unread)
                self.chat_changed.emit(chat)
        elif isinstance(update, t.UpdateDialogPinned) and isinstance(update.peer, t.DialogPeer):
            chat = self.chats.get(utils.get_peer_id(update.peer.peer))
            if chat:
                chat.pinned = bool(update.pinned)
                chat.pin_rank = -1  # newly pinned chats go on top
                self.chat_changed.emit(chat)
        elif isinstance(update, t.UpdatePinnedDialogs) and update.order is not None:
            for rank, dp in enumerate(update.order):
                if isinstance(dp, t.DialogPeer):
                    chat = self.chats.get(utils.get_peer_id(dp.peer))
                    if chat:
                        chat.pinned, chat.pin_rank = True, rank
                        self.chat_changed.emit(chat)
        elif isinstance(update, (t.UpdateDialogFilter, t.UpdateDialogFilterOrder, t.UpdateDialogFilters)):
            await self.load_folders()


# --- helpers ---------------------------------------------------------------


def fill_reply(reply: ReplyInfo, msg) -> None:
    if msg is None:
        reply.sender = reply.sender or ""
        reply.text = reply.text or "Сообщение удалено"
        return
    item = message_from_telethon(msg)
    reply.sender = item.sender_name
    reply.sender_id = item.sender_id
    if not reply.text:
        reply.text = item.preview


def action_text(event) -> str:
    if event.uploading:
        return "отправляет файл…"
    if event.recording or event.audio:
        return "записывает голосовое…"
    if event.round or event.video:
        return "записывает видео…"
    if event.sticker:
        return "выбирает стикер…"
    return "печатает…"


def plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def presence_text(status) -> str:
    from datetime import datetime, timezone

    if isinstance(status, t.UserStatusOnline):
        return "в сети"
    if isinstance(status, t.UserStatusOffline):
        seen = status.was_online.astimezone()
        now = datetime.now(timezone.utc).astimezone()
        delta = now - seen
        if delta.total_seconds() < 60:
            return "был(а) только что"
        if delta.total_seconds() < 3600:
            m = int(delta.total_seconds() // 60)
            return f"был(а) {m} {plural(m, 'минуту', 'минуты', 'минут')} назад"
        if seen.date() == now.date():
            return f"был(а) сегодня в {seen:%H:%M}"
        if (now.date() - seen.date()).days == 1:
            return f"был(а) вчера в {seen:%H:%M}"
        return f"был(а) {seen:%d.%m.%y}"
    if isinstance(status, t.UserStatusRecently):
        return "был(а) недавно"
    if isinstance(status, t.UserStatusLastWeek):
        return "был(а) на этой неделе"
    if isinstance(status, t.UserStatusLastMonth):
        return "был(а) в этом месяце"
    return "был(а) давно"


def write_atomic(path: Path, data: bytes) -> Path:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path
