import unittest
from datetime import datetime

from telegram_personal_messenger.formatting import (
    avatar_color,
    chats_word,
    day_key,
    format_chat_time,
    format_date_separator,
    format_message_time,
    initials,
    plural,
    preview,
    unread_text,
    views_text,
)


class TimeFormattingTests(unittest.TestCase):
    now = datetime(2026, 3, 12, 15, 30)

    def test_today_shows_time(self):
        self.assertEqual(
            format_chat_time(datetime(2026, 3, 12, 9, 5), self.now),
            "09:05",
        )

    def test_yesterday_and_this_year(self):
        self.assertEqual(
            format_chat_time(datetime(2026, 3, 11, 23, 0), self.now),
            "Вчера",
        )
        self.assertEqual(
            format_chat_time(datetime(2026, 2, 3, 12, 0), self.now),
            "3 фев",
        )

    def test_previous_year(self):
        self.assertEqual(
            format_chat_time(datetime(2025, 12, 31, 12, 0), self.now),
            "31.12.25",
        )

    def test_none_is_empty(self):
        self.assertEqual(format_chat_time(None, self.now), "")

    def test_message_time(self):
        self.assertEqual(format_message_time(datetime(2026, 3, 12, 9, 5)), "09:05")

    def test_date_separators(self):
        self.assertEqual(format_date_separator(datetime(2026, 3, 12, 9), self.now), "Сегодня")
        self.assertEqual(format_date_separator(datetime(2026, 3, 11, 9), self.now), "Вчера")
        self.assertEqual(
            format_date_separator(datetime(2026, 3, 3, 9), self.now),
            "3 марта",
        )
        self.assertEqual(
            format_date_separator(datetime(2025, 3, 3, 9), self.now),
            "3 марта 2025",
        )

    def test_day_key(self):
        self.assertEqual(day_key(datetime(2026, 3, 12, 23, 59)), datetime(2026, 3, 12).date())


class NameFormattingTests(unittest.TestCase):
    def test_initials(self):
        self.assertEqual(initials("Аня Соколова"), "АС")
        self.assertEqual(initials("Telegram"), "T")
        self.assertEqual(initials("  "), "?")
        self.assertEqual(initials("@username"), "U")

    def test_avatar_color_is_stable_and_from_palette(self):
        self.assertEqual(avatar_color(42), avatar_color(42))
        self.assertRegex(avatar_color(42), r"^#[0-9A-F]{6}$")

    def test_preview_collapses_and_truncates(self):
        self.assertEqual(preview("  a\n b\t c "), "a b c")
        self.assertEqual(preview("abcdef", limit=4), "abc…")
        self.assertEqual(preview("", limit=4), "")

    def test_unread_text(self):
        self.assertEqual(unread_text(0), "")
        self.assertEqual(unread_text(7), "7")
        self.assertEqual(unread_text(100), "99+")

    def test_views_text(self):
        self.assertEqual(views_text(None), "")
        self.assertEqual(views_text(0), "0")
        self.assertEqual(views_text(999), "999")
        self.assertEqual(views_text(1500), "1,5K")
        self.assertEqual(views_text(1_000_000), "1M")
        self.assertEqual(views_text(2_400_000), "2,4M")


class PluralTests(unittest.TestCase):
    def test_russian_plural(self):
        self.assertEqual(plural(1, "чат", "чата", "чатов"), "чат")
        self.assertEqual(plural(2, "чат", "чата", "чатов"), "чата")
        self.assertEqual(plural(5, "чат", "чата", "чатов"), "чатов")
        self.assertEqual(plural(11, "чат", "чата", "чатов"), "чатов")
        self.assertEqual(plural(21, "чат", "чата", "чатов"), "чат")

    def test_chats_word(self):
        self.assertEqual(chats_word(3), "чата")
        self.assertEqual(chats_word(12), "чатов")


if __name__ == "__main__":
    unittest.main()
