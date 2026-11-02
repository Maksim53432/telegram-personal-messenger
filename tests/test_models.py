import unittest

from telegram_personal_messenger.models import Recipient, SendOutcome, validate_message


class ModelTests(unittest.TestCase):
    def test_rejects_empty_or_whitespace_message(self):
        for text in ("", "   ", "\n\t"):
            with self.subTest(text=repr(text)), self.assertRaises(ValueError):
                validate_message(text)

    def test_preserves_valid_message_without_splitting(self):
        text = "  hello, кот!  "
        self.assertEqual(validate_message(text), text)

    def test_recipient_and_outcome_keep_only_safe_fields(self):
        recipient = Recipient(id=7, display_name="Alex", username="alex")
        result = SendOutcome(kind="unknown", message="Delivery result is unknown.")

        self.assertEqual(recipient.username, "alex")
        self.assertEqual(result.kind, "unknown")
        self.assertEqual(result.message, "Delivery result is unknown.")


if __name__ == "__main__":
    unittest.main()
