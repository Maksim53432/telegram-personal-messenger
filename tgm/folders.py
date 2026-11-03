"""Telegram chat folders (dialog filters), matched locally against loaded chats."""

from __future__ import annotations

from dataclasses import dataclass, field

from telethon import utils
from telethon.tl import types as t

from .models import ChatItem

ALL_ID = 0
ARCHIVE_ID = -1


@dataclass
class Folder:
    id: int
    title: str
    include: set[int] = field(default_factory=set)
    exclude: set[int] = field(default_factory=set)
    pinned: list[int] = field(default_factory=list)
    contacts: bool = False
    non_contacts: bool = False
    groups: bool = False
    channels: bool = False
    bots: bool = False
    exclude_muted: bool = False
    exclude_read: bool = False
    exclude_archived: bool = False

    def contains(self, chat: ChatItem) -> bool:
        if self.id == ALL_ID:
            return chat.in_dialogs and not chat.archived
        if self.id == ARCHIVE_ID:
            return chat.in_dialogs and chat.archived
        pid = chat.peer_id
        if pid in self.pinned or pid in self.include:
            return True
        if pid in self.exclude or not chat.in_dialogs:
            return False
        if self.exclude_muted and chat.muted:
            return False
        if self.exclude_read and not (chat.unread or chat.unread_mark):
            return False
        if self.exclude_archived and chat.archived:
            return False
        kind = chat.kind
        if kind in ("user", "self"):
            return self.contacts if chat.is_contact else self.non_contacts
        if kind == "bot":
            return self.bots
        if kind == "group":
            return self.groups
        if kind == "channel":
            return self.channels
        return False

    def rank(self, chat: ChatItem) -> tuple:
        """Sort key: pinned chats first in their own order, then newest first."""
        if self.id in (ALL_ID, ARCHIVE_ID):
            if chat.pinned:
                return (0, chat.pin_rank, 0.0)
        elif chat.peer_id in self.pinned:
            return (0, self.pinned.index(chat.peer_id), 0.0)
        return (1, 0, -chat.sort_date)

    def is_pinned(self, chat: ChatItem) -> bool:
        if self.id in (ALL_ID, ARCHIVE_ID):
            return chat.pinned
        return chat.peer_id in self.pinned


BUILTIN = [Folder(ALL_ID, "Все чаты"), Folder(ARCHIVE_ID, "Архив")]


def _peer_ids(peers) -> list[int]:
    ids = []
    for p in peers or []:
        try:
            ids.append(utils.get_peer_id(p))
        except (TypeError, ValueError):
            pass
    return ids


def _title(value) -> str:
    return getattr(value, "text", value) or ""


def folder_from_filter(f) -> Folder | None:
    if isinstance(f, t.DialogFilter):
        return Folder(
            id=f.id,
            title=_title(f.title),
            include=set(_peer_ids(f.include_peers)),
            exclude=set(_peer_ids(f.exclude_peers)),
            pinned=_peer_ids(f.pinned_peers),
            contacts=bool(f.contacts),
            non_contacts=bool(f.non_contacts),
            groups=bool(f.groups),
            channels=bool(f.broadcasts),
            bots=bool(f.bots),
            exclude_muted=bool(f.exclude_muted),
            exclude_read=bool(f.exclude_read),
            exclude_archived=bool(f.exclude_archived),
        )
    if isinstance(f, t.DialogFilterChatlist):
        return Folder(
            id=f.id,
            title=_title(f.title),
            include=set(_peer_ids(f.include_peers)),
            pinned=_peer_ids(f.pinned_peers),
        )
    return None
