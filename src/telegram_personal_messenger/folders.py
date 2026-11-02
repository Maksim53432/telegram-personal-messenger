"""Правила пользовательских папок Telegram и сортировка чатов."""

from __future__ import annotations

from .models import Chat, Folder

ALL_FOLDER_KEY = "all"
ARCHIVE_FOLDER_KEY = "archive"


def all_folder() -> Folder:
    return Folder(key=ALL_FOLDER_KEY, title="Все чаты", kind="all")


def archive_folder() -> Folder:
    return Folder(key=ARCHIVE_FOLDER_KEY, title="Архив", kind="archive")


def chat_matches(folder: Folder, chat: Chat) -> bool:
    """Проверяет, попадает ли чат в папку по правилам Telegram."""

    if folder.kind == "all":
        return not chat.archived
    if folder.kind == "archive":
        return chat.archived

    if chat.id in folder.exclude_peers:
        return False

    # Явно закреплённые и добавленные в папку чаты показываются всегда.
    if chat.id in folder.pinned_peers or chat.id in folder.include_peers:
        return True

    if folder.exclude_archived and chat.archived:
        return False
    if folder.exclude_muted and chat.muted:
        return False
    if folder.exclude_read and chat.unread == 0:
        return False

    if chat.is_bot:
        return folder.bots
    if chat.is_user:
        return folder.contacts if chat.is_contact else folder.non_contacts
    if chat.is_group:
        return folder.groups
    if chat.is_channel:
        return folder.broadcasts
    return False


def chats_in_folder(folder: Folder, chats: list[Chat]) -> list[Chat]:
    visible = [chat for chat in chats if chat_matches(folder, chat)]
    return sort_chats(visible)


def sort_chats(chats: list[Chat]) -> list[Chat]:
    """Закреплённые сверху, дальше — по времени последнего сообщения."""

    return sorted(
        chats,
        key=lambda chat: (not chat.pinned, -_timestamp(chat)),
    )


def folder_label(folder: Folder) -> str:
    title = folder.title.strip() or "Без названия"
    if folder.emoticon:
        return f"{folder.emoticon} {title}"
    return title


def _timestamp(chat: Chat) -> float:
    if chat.date is None:
        return 0.0
    try:
        return chat.date.timestamp()
    except (OSError, OverflowError, ValueError):
        return 0.0
