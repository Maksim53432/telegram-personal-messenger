import unittest
from datetime import datetime, timedelta

from telegram_personal_messenger.folders import (
    ALL_FOLDER_KEY,
    ARCHIVE_FOLDER_KEY,
    all_folder,
    archive_folder,
    chat_matches,
    chats_in_folder,
    folder_label,
    sort_chats,
)
from telegram_personal_messenger.models import Chat, Folder


def make_chat(
    chat_id: int,
    *,
    kind: str = "user",
    contact: bool = False,
    archived: bool = False,
    muted: bool = False,
    unread: int = 0,
    pinned: bool = False,
    minutes: int = 0,
) -> Chat:
    return Chat(
        id=chat_id,
        title=f"Chat {chat_id}",
        kind=kind,
        is_contact=contact,
        archived=archived,
        muted=muted,
        unread=unread,
        pinned=pinned,
        date=datetime(2026, 1, 1, 12, 0) + timedelta(minutes=minutes),
    )


class DefaultFolderTests(unittest.TestCase):
    def test_all_excludes_archive_and_archive_contains_only_archived(self):
        chats = [make_chat(1), make_chat(2, archived=True)]
        self.assertEqual(
            [chat.id for chat in chats_in_folder(all_folder(), chats)],
            [1],
        )
        self.assertEqual(
            [chat.id for chat in chats_in_folder(archive_folder(), chats)],
            [2],
        )

    def test_folder_keys(self):
        self.assertEqual(all_folder().key, ALL_FOLDER_KEY)
        self.assertEqual(archive_folder().key, ARCHIVE_FOLDER_KEY)


class CustomFolderTests(unittest.TestCase):
    def test_contacts_non_contacts_groups_broadcasts_and_bots(self):
        folder = Folder(
            key="folder:2",
            title="Люди и каналы",
            contacts=True,
            non_contacts=True,
            groups=True,
            broadcasts=True,
            bots=True,
        )
        chats = [
            make_chat(1, contact=True),
            make_chat(2, contact=False),
            make_chat(3, kind="group"),
            make_chat(4, kind="channel"),
            make_chat(5, kind="bot"),
        ]
        self.assertEqual(
            {chat.id for chat in chats_in_folder(folder, chats)},
            {1, 2, 3, 4, 5},
        )

    def test_type_flags_select_only_matching_kind(self):
        groups = Folder(key="folder:2", title="Группы", groups=True)
        chats = [
            make_chat(1),
            make_chat(2, kind="group"),
            make_chat(3, kind="channel"),
        ]
        self.assertEqual(
            [chat.id for chat in chats_in_folder(groups, chats)],
            [2],
        )

    def test_include_and_pinned_override_type_flags(self):
        folder = Folder(
            key="folder:2",
            title="Избранное",
            include_peers=frozenset({2}),
            pinned_peers=frozenset({3}),
        )
        chats = [make_chat(1), make_chat(2), make_chat(3, archived=True)]
        self.assertEqual(
            {chat.id for chat in chats_in_folder(folder, chats)},
            {2, 3},
        )

    def test_exclude_peers_wins_over_include(self):
        folder = Folder(
            key="folder:2",
            title="Без одного",
            contacts=True,
            include_peers=frozenset({1}),
            exclude_peers=frozenset({1}),
        )
        self.assertFalse(chat_matches(folder, make_chat(1, contact=True)))

    def test_exclude_muted_read_and_archived(self):
        folder = Folder(
            key="folder:2",
            title="Входящие",
            non_contacts=True,
            exclude_muted=True,
            exclude_read=True,
            exclude_archived=True,
        )
        chats = [
            make_chat(1, unread=2),
            make_chat(2, unread=0),
            make_chat(3, unread=1, muted=True),
            make_chat(4, unread=1, archived=True),
        ]
        self.assertEqual(
            [chat.id for chat in chats_in_folder(folder, chats)],
            [1],
        )

    def test_empty_custom_folder_matches_nothing(self):
        folder = Folder(key="folder:2", title="Пустая")
        self.assertEqual(chats_in_folder(folder, [make_chat(1)]), [])

    def test_folder_label_uses_emoticon(self):
        folder = Folder(key="folder:2", title="Работа", emoticon="💼")
        self.assertEqual(folder_label(folder), "💼 Работа")
        self.assertEqual(folder_label(Folder(key="folder:3", title="  ")), "Без названия")


class SortingTests(unittest.TestCase):
    def test_pinned_first_then_newest(self):
        chats = [
            make_chat(1, minutes=10),
            make_chat(2, minutes=30),
            make_chat(3, minutes=0, pinned=True),
        ]
        self.assertEqual([chat.id for chat in sort_chats(chats)], [3, 2, 1])

    def test_chats_without_date_are_last(self):
        dated = make_chat(1, minutes=5)
        undated = Chat(id=2, title="No date")
        self.assertEqual([chat.id for chat in sort_chats([undated, dated])], [1, 2])


if __name__ == "__main__":
    unittest.main()
