import unittest
from datetime import datetime, timedelta

from telegram_personal_messenger.folders import all_folder, archive_folder
from telegram_personal_messenger.models import Chat, Folder, Message
from telegram_personal_messenger.state import ChatStore, message_preview


def chat(chat_id: int, *, title: str | None = None, username: str | None = None, unread: int = 0, minutes: int = 0) -> Chat:
    return Chat(
        id=chat_id,
        title=title or f"Chat {chat_id}",
        username=username,
        unread=unread,
        date=datetime(2026, 1, 1, 12, 0) + timedelta(minutes=minutes),
    )


def message(chat_id: int, text: str = "hello", *, out: bool = False, media: str | None = None) -> Message:
    return Message(
        id=1,
        chat_id=chat_id,
        text=text,
        date=datetime(2026, 1, 1, 12, 30),
        out=out,
        media=media,
    )


class ChatStoreTests(unittest.TestCase):
    def make_store(self) -> ChatStore:
        return ChatStore(
            [chat(1, title="Аня", username="anya", unread=2, minutes=5), chat(2, title="Работа", minutes=10)],
            [all_folder(), archive_folder(), Folder(key="folder:2", title="Люди", contacts=True)],
        )

    def test_defaults_to_all_folder_and_shows_newest_first(self):
        store = self.make_store()
        self.assertEqual(store.folder_key, "all")
        self.assertEqual([item.id for item in store.visible_chats()], [2, 1])

    def test_search_matches_title_and_username_and_ignores_at(self):
        store = self.make_store()
        store.set_query("аня")
        self.assertEqual([item.id for item in store.visible_chats()], [1])
        store.set_query("@anya")
        self.assertEqual([item.id for item in store.visible_chats()], [1])

    def test_search_returns_empty_when_nothing_matches(self):
        store = self.make_store()
        store.set_query("missing")
        self.assertEqual(store.visible_chats(), [])

    def test_folder_counts_ignore_search(self):
        store = self.make_store()
        store.set_query("аня")
        self.assertEqual(store.folder_counts()["all"], 2)

    def test_select_and_mark_read(self):
        store = self.make_store()
        store.select(1)
        self.assertEqual(store.selected.id, 1)
        self.assertTrue(store.mark_read(1))
        self.assertEqual(store.chat(1).unread, 0)
        self.assertFalse(store.mark_read(1))

    def test_load_preserves_selection_and_falls_back_to_all(self):
        store = self.make_store()
        store.select(1)
        store.set_folder("folder:2")
        store.load([chat(1), chat(3)], [all_folder(), archive_folder()])
        self.assertEqual(store.selected_id, 1)
        self.assertEqual(store.folder_key, "all")

    def test_load_drops_missing_selection(self):
        store = self.make_store()
        store.select(2)
        store.load([chat(1)], [all_folder(), archive_folder()])
        self.assertIsNone(store.selected_id)

    def test_add_chat_sets_date_and_overwrites(self):
        store = self.make_store()
        store.add_chat(Chat(id=9, title="Новый", username="new"))
        self.assertIsNotNone(store.chat(9).date)
        store.add_chat(Chat(id=9, title="Обновлён"))
        self.assertEqual(store.chat(9).title, "Обновлён")

    def test_apply_incoming_increments_unread_for_inactive_chat(self):
        store = self.make_store()
        self.assertTrue(store.apply_message(message(2)))
        chat_two = store.chat(2)
        self.assertEqual(chat_two.unread, 1)
        self.assertEqual(chat_two.last_message, "hello")
        self.assertFalse(chat_two.last_out)

    def test_apply_incoming_for_selected_chat_stays_read(self):
        store = self.make_store()
        store.select(2)
        store.apply_message(message(2))
        self.assertEqual(store.chat(2).unread, 0)

    def test_own_message_resets_unread(self):
        store = self.make_store()
        store.apply_message(message(1, out=True))
        self.assertEqual(store.chat(1).unread, 0)
        self.assertTrue(store.chat(1).last_out)

    def test_apply_message_for_unknown_chat_reports_false(self):
        store = self.make_store()
        self.assertFalse(store.apply_message(message(99)))

    def test_unread_total(self):
        store = self.make_store()
        self.assertEqual(store.unread_total(), 2)


class PreviewTests(unittest.TestCase):
    def test_text_is_collapsed(self):
        self.assertEqual(message_preview(message(1, "  hello \n world  ")), "hello world")

    def test_media_is_included(self):
        self.assertEqual(
            message_preview(message(1, "подпись", media="Фото")),
            "Фото · подпись",
        )
        self.assertEqual(message_preview(message(1, "", media="Фото")), "Фото")

    def test_long_text_is_truncated(self):
        preview = message_preview(message(1, "a" * 200))
        self.assertTrue(preview.endswith("…"))
        self.assertLessEqual(len(preview), 80)


if __name__ == "__main__":
    unittest.main()
