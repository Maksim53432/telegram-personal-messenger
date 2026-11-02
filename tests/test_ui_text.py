import unittest

from telegram_personal_messenger import errors
from telegram_personal_messenger.errors import TelegramServiceError
from telegram_personal_messenger.models import Account, Chat, Message, SendOutcome
from telegram_personal_messenger.ui import outcome_tone
from telegram_personal_messenger.ui.text import (
    account_handle,
    account_title,
    chat_subtitle,
    error_text,
    last_message_line,
    message_counter,
    outcome_text,
    short_username,
)


class ErrorTextTests(unittest.TestCase):
    def test_known_error_codes_are_translated(self):
        self.assertIn("интернет", error_text(errors.CONNECTION))
        self.assertIn("Код", error_text(errors.LOGIN_CODE_INVALID))
        self.assertIn("@username", error_text(errors.USERNAME_NOT_FOUND))

    def test_flood_wait_reports_seconds(self):
        message = error_text(errors.FLOOD_WAIT, seconds=12)
        self.assertIn("12 секунд", message)
        self.assertIn("подождать", message)

    def test_exception_with_code_is_translated(self):
        self.assertEqual(
            error_text(TelegramServiceError(errors.USERNAME_INVALID)),
            error_text(errors.USERNAME_INVALID),
        )

    def test_unknown_error_is_safe(self):
        self.assertNotIn("raw", error_text(RuntimeError("raw details")))

    def test_outcome_text(self):
        self.assertEqual(outcome_text(SendOutcome("sent", "sent")), "Сообщение отправлено.")
        self.assertIn("не повторяло", outcome_text(SendOutcome("unknown", errors.SEND_UNKNOWN)))
        self.assertIn("Сначала", outcome_text(SendOutcome("failed", "empty")))
        self.assertIn("4096", outcome_text(SendOutcome("failed", "too_long")))
        self.assertIn("30 секунд", outcome_text(SendOutcome("failed", errors.FLOOD_WAIT, seconds=30)))

    def test_outcome_tone(self):
        self.assertEqual(outcome_tone(SendOutcome("unknown", errors.SEND_UNKNOWN)), "warning")
        self.assertEqual(outcome_tone(SendOutcome("failed", errors.SEND_FAILED)), "error")


class ChatTextTests(unittest.TestCase):
    def test_chat_subtitle_for_user_group_channel_and_archive(self):
        self.assertEqual(chat_subtitle(Chat(1, "A", "alex")), "@alex")
        self.assertEqual(chat_subtitle(Chat(1, "A")), "Личный чат")
        self.assertEqual(chat_subtitle(Chat(1, "G", kind="group")), "Группа")
        self.assertEqual(chat_subtitle(Chat(1, "C", kind="channel")), "Канал")
        self.assertEqual(chat_subtitle(Chat(1, "B", kind="bot")), "Бот")
        self.assertEqual(
            chat_subtitle(Chat(1, "G", kind="group", archived=True)),
            "Группа · архив",
        )

    def test_last_message_line(self):
        self.assertEqual(last_message_line(Chat(1, "A")), "Нет сообщений")
        self.assertEqual(
            last_message_line(Chat(1, "A", last_message="привет")),
            "привет",
        )
        self.assertEqual(
            last_message_line(Chat(1, "A", last_message="привет", last_out=True)),
            "Вы: привет",
        )

    def test_account_helpers(self):
        account = Account(1, "Максим", "max")
        self.assertEqual(account_handle(account), "@max")
        self.assertEqual(account_title(account), "Максим")
        self.assertEqual(account_handle(None), "")
        self.assertEqual(account_title(None), "Аккаунт")

    def test_message_counter_and_short_username(self):
        self.assertEqual(message_counter(5, 4096), "5 / 4096")
        self.assertEqual(short_username(" @very_long_username "), "very_long_username")


if __name__ == "__main__":
    unittest.main()
