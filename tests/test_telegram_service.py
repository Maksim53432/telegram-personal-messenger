import asyncio
from pathlib import Path
import unittest

from telethon.errors import PhoneCodeInvalidError, RPCError, SessionPasswordNeededError

from telegram_personal_messenger.config import Settings
from telegram_personal_messenger.models import Recipient
from telegram_personal_messenger.telegram_service import TelegramService, TelegramServiceError


class FakeUser:
    def __init__(self, user_id=7, first_name="Alex", last_name="", username="alex"):
        self.id = user_id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username


class FakeGroup:
    id = 99
    title = "Not a person"


class FakeDialog:
    def __init__(self, entity):
        self.entity = entity


class FakeClient:
    def __init__(self, entity=None, dialogs=None):
        self.entity = entity or FakeUser()
        self.dialogs = dialogs if dialogs is not None else [FakeDialog(self.entity)]
        self.connected = False
        self.authorized = False
        self.send_calls = []
        self.send_error = None
        self.sign_in_error = None

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return self.authorized

    async def send_code_request(self, phone):
        self.phone_for_code = phone

    async def sign_in(self, phone=None, code=None, password=None):
        if self.sign_in_error is not None:
            raise self.sign_in_error

    async def get_dialogs(self):
        return self.dialogs

    async def get_entity(self, username):
        if username != "alex":
            raise ValueError("private lookup detail")
        return self.entity

    async def send_message(self, entity, text, parse_mode="markdown"):
        self.send_calls.append((entity, text, parse_mode))
        if self.send_error is not None:
            raise self.send_error


class TelegramServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, client):
        settings = Settings(12345, "x" * 32, Path("unused-session"))
        return TelegramService(
            settings,
            client_factory=lambda *args, **kwargs: client,
            user_type=FakeUser,
        )

    async def test_existing_session_authorization_state_is_reported(self):
        client = FakeClient()
        client.authorized = True
        service = self.make_service(client)

        self.assertTrue(await service.is_authorized())

    async def test_username_resolution_normalizes_optional_at(self):
        client = FakeClient()
        service = self.make_service(client)

        recipient = await service.resolve_username("@alex")

        self.assertEqual(recipient, Recipient(7, "Alex", "alex"))

    async def test_unresolved_username_has_safe_error(self):
        service = self.make_service(FakeClient())

        with self.assertRaises(TelegramServiceError) as error:
            await service.resolve_username("missing")

        self.assertNotIn("private lookup detail", str(error.exception))

    async def test_username_resolving_to_group_is_rejected(self):
        client = FakeClient(entity=FakeGroup())
        service = self.make_service(client)

        with self.assertRaises(TelegramServiceError):
            await service.resolve_username("alex")

        self.assertEqual(client.send_calls, [])

    async def test_dialog_list_contains_only_individual_users(self):
        user = FakeUser()
        client = FakeClient(dialogs=[FakeDialog(user), FakeDialog(FakeGroup())])
        service = self.make_service(client)

        recipients = await service.list_recipients()

        self.assertEqual(recipients, [Recipient(7, "Alex", "alex")])

    async def test_one_send_invokes_client_once_and_preserves_text(self):
        client = FakeClient()
        service = self.make_service(client)
        recipient = await service.resolve_username("alex")

        text = "keep _underscores_ and *stars* literally"
        outcome = await service.send_message(recipient, text)

        self.assertEqual(outcome.kind, "sent")
        self.assertEqual(client.send_calls, [(client.entity, text, None)])

    async def test_password_required_is_returned_as_auth_state(self):
        client = FakeClient()
        client.sign_in_error = SessionPasswordNeededError(None)
        service = self.make_service(client)

        state = await service.sign_in_code("+10000000000", "12345")

        self.assertEqual(state, "password_required")

    async def test_invalid_login_code_is_sanitized(self):
        client = FakeClient()
        client.sign_in_error = PhoneCodeInvalidError(None)
        service = self.make_service(client)

        with self.assertRaises(TelegramServiceError) as error:
            await service.sign_in_code("+10000000000", "12345")

        self.assertNotIn("12345", str(error.exception))

    async def test_rpc_rejection_is_failed_without_raw_error_details(self):
        client = FakeClient()
        client.send_error = RPCError(None, "CHAT_WRITE_FORBIDDEN_SECRET", 403)
        service = self.make_service(client)
        recipient = await service.resolve_username("alex")

        outcome = await service.send_message(recipient, "hello")

        self.assertEqual(outcome.kind, "failed")
        self.assertNotIn("CHAT_WRITE_FORBIDDEN_SECRET", outcome.message)
        self.assertEqual(len(client.send_calls), 1)

    async def test_timeout_is_unknown_and_is_not_retried(self):
        client = FakeClient()
        client.send_error = asyncio.TimeoutError()
        service = self.make_service(client)
        recipient = await service.resolve_username("alex")

        outcome = await service.send_message(recipient, "hello")

        self.assertEqual(outcome.kind, "unknown")
        self.assertEqual(len(client.send_calls), 1)


if __name__ == "__main__":
    unittest.main()
