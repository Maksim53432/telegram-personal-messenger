import unittest
from datetime import datetime

from telegram_personal_messenger.models import (
    MAX_MESSAGE_LENGTH,
    Chat,
    Message,
    MessageValidationError,
    Reaction,
    SendOutcome,
    validate_message,
)


class MessageValidationTests(unittest.TestCase):
    def test_rejects_empty_or_whitespace_message_with_code(self):
        for text in ("", "   ", "\n\t"):
            with self.subTest(text=repr(text)), self.assertRaises(MessageValidationError) as error:
                validate_message(text)
            self.assertEqual(error.exception.code, "empty")

    def test_rejects_message_longer_than_telegram_limit(self):
        with self.assertRaises(MessageValidationError) as error:
            validate_message("a" * (MAX_MESSAGE_LENGTH + 1))
        self.assertEqual(error.exception.code, "too_long")

    def test_accepts_message_at_limit_and_preserves_whitespace(self):
        text = " " + "a" * (MAX_MESSAGE_LENGTH - 2) + " "
        self.assertEqual(validate_message(text), text)

    def test_preserves_valid_message_without_splitting(self):
        text = "  hello, кот!  "
        self.assertEqual(validate_message(text), text)


class ModelTests(unittest.TestCase):
    def test_chat_kind_properties(self):
        self.assertTrue(Chat(1, "A", kind="user").is_user)
        self.assertTrue(Chat(1, "A", kind="bot").is_bot)
        self.assertTrue(Chat(1, "A", kind="group").is_group)
        self.assertTrue(Chat(1, "A", kind="channel").is_channel)
        self.assertFalse(Chat(1, "A", kind="group").is_user)

    def test_message_empty_predicate(self):
        now = datetime(2026, 1, 1, 12, 0)
        self.assertTrue(Message(1, 2, "", now).is_empty)
        self.assertFalse(Message(1, 2, "", now, media="Фото").is_empty)
        self.assertFalse(Message(1, 2, "text", now).is_empty)

    def test_send_outcome_keeps_only_safe_fields(self):
        result = SendOutcome(kind="unknown", code="send_unknown")
        self.assertEqual(result.kind, "unknown")
        self.assertEqual(result.code, "send_unknown")
        self.assertIsNone(result.sent_message)

    def test_chat_has_avatar_and_forum_metadata_defaults(self):
        chat = Chat(1, "A")
        self.assertFalse(chat.photo_available)
        self.assertIsNone(chat.participants_count)
        self.assertFalse(chat.is_forum)

        chat = Chat(
            1,
            "Group",
            kind="group",
            photo_available=True,
            participants_count=42,
            is_forum=True,
        )
        self.assertTrue(chat.photo_available)
        self.assertEqual(chat.participants_count, 42)
        self.assertTrue(chat.is_forum)

    def test_message_metadata_and_reaction_defaults(self):
        now = datetime(2026, 1, 1, 12, 0)
        message = Message(1, 2, "text", now)
        self.assertIsNone(message.media_kind)
        self.assertIsNone(message.forwarded_from)
        self.assertFalse(message.pinned)
        self.assertFalse(message.edited)
        self.assertIsNone(message.views)
        self.assertIsNone(message.grouped_id)
        self.assertEqual(message.reactions, ())

        message = Message(
            1,
            2,
            "text",
            now,
            media_kind="photo",
            pinned=True,
            edited=True,
            reactions=(Reaction("👍", 3, True),),
        )
        self.assertEqual(message.media_kind, "photo")
        self.assertTrue(message.pinned)
        self.assertTrue(message.edited)
        self.assertEqual(message.reactions[0].emoticon, "👍")
        self.assertTrue(message.reactions[0].chosen)


if __name__ == "__main__":
    unittest.main()
