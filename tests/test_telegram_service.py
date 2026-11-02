import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest

from telethon.errors import (
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    RPCError,
    SessionPasswordNeededError,
)
from telethon.tl.types import (
    DialogFilter,
    InputPeerChannel,
    InputPeerUser,
    TextWithEntities,
    User,
)

from telegram_personal_messenger import errors
from telegram_personal_messenger.config import Proxy, Settings
from telegram_personal_messenger.errors import TelegramServiceError
from telegram_personal_messenger.telegram_service import TelegramService

NOW = datetime(2026, 3, 12, 15, 0, tzinfo=timezone.utc)


class FakeEntity:
    def __init__(self, entity_id, title, *, username=None, contact=False, bot=False, deleted=False):
        self.id = entity_id
        self.title = title
        self.username = username
        self.contact = contact
        self.bot = bot
        self.deleted = deleted


class FakeMessage:
    def __init__(
        self,
        message_id,
        chat_id,
        text,
        *,
        out=False,
        sender=None,
        media=None,
        date=NOW,
        reply_to=None,
    ):
        self.id = message_id
        self.chat_id = chat_id
        self.message = text
        self.text = text
        self.out = out
        self.sender = sender
        self.sender_id = getattr(sender, "id", None)
        self.date = date
        self.reply_to_msg_id = reply_to
        self.photo = object() if media == "photo" else None
        self.video = object() if media == "video" else None
        self.voice = object() if media == "voice" else None
        self.video_note = object() if media == "round" else None
        self.sticker = object() if media == "sticker" else None
        self.gif = object() if media == "gif" else None
        self.audio = object() if media == "audio" else None
        self.document = object() if media == "document" else None
        self.geo = object() if media == "geo" else None
        self.contact = object() if media == "contact" else None
        self.poll = None
        self.dice = None
        self.file = SimpleNamespace(name="report.pdf") if media == "document" else None


class FakeDialog:
    def __init__(
        self,
        entity,
        *,
        dialog_id,
        name=None,
        message=None,
        date=NOW,
        unread=0,
        pinned=False,
        archived=False,
        is_user=False,
        is_group=False,
        is_channel=False,
        muted=False,
    ):
        self.entity = entity
        self.id = dialog_id
        self.name = name or getattr(entity, "title", None) or getattr(entity, "first_name", "")
        self.title = self.name
        self.message = message
        self.date = date
        self.unread_count = unread
        self.pinned = pinned
        self.archived = archived
        self.folder_id = 1 if archived else None
        self.is_user = is_user
        self.is_group = is_group
        self.is_channel = is_channel
        self.dialog = SimpleNamespace(
            notify_settings=SimpleNamespace(
                mute_until=datetime.now(timezone.utc) + timedelta(days=1) if muted else None
            )
        )


class FakeClient:
    def __init__(self):
        self.connected = False
        self.authorized = False
        self.dialogs = []
        self.filters = []
        self.messages = []
        self.entity = None
        self.phone = None
        self.sign_in_error = None
        self.send_error = None
        self.sent_message = None
        self.send_calls = []
        self.message_calls = []
        self.dialog_limit = "unset"
        self.session = SimpleNamespace(save=lambda: "session-value")
        self.connected_calls = 0

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True
        self.connected_calls += 1

    async def disconnect(self):
        self.connected = False

    async def is_user_authorized(self):
        return self.authorized

    async def get_me(self):
        return User(id=7, first_name="Alex", last_name="Smith", username="alex")

    async def send_code_request(self, phone):
        self.phone = phone

    async def sign_in(self, phone=None, code=None, password=None):
        if self.sign_in_error is not None:
            raise self.sign_in_error

    async def get_dialogs(self, limit=None):
        self.dialog_limit = limit
        return self.dialogs

    async def __call__(self, request):
        return SimpleNamespace(filters=self.filters)

    async def get_entity(self, target):
        if target == "missing":
            raise ValueError("private lookup detail")
        return self.entity

    async def get_messages(self, entity, limit=60, offset_id=0):
        self.message_calls.append((entity, limit, offset_id))
        return self.messages

    async def send_message(self, entity, text, parse_mode=None):
        self.send_calls.append((entity, text, parse_mode))
        if self.send_error is not None:
            raise self.send_error
        return self.sent_message

    async def send_read_acknowledge(self, entity, clear_mentions=False):
        self.read_entity = entity


class TelegramServiceTests(unittest.IsolatedAsyncioTestCase):
    def make_service(self, client: FakeClient) -> TelegramService:
        settings = Settings(12345, "x" * 32, Path("/tmp/tpm-test/session"))
        return TelegramService(
            settings,
            client_factory=lambda *args, **kwargs: client,
        )

    async def test_existing_session_authorization_state_is_reported(self):
        client = FakeClient()
        client.authorized = True
        service = self.make_service(client)

        self.assertTrue(await service.is_authorized())
        self.assertEqual(client.dialog_limit, "unset")

    def test_proxy_is_passed_to_client_factory(self):
        captured = {}

        def factory(*args, **kwargs):
            captured.update(kwargs)
            return FakeClient()

        settings = Settings(
            12345,
            "x" * 32,
            Path("/tmp/tpm-test/session"),
            proxy=Proxy("socks5", "127.0.0.1", 18080),
        )
        TelegramService(settings, client_factory=factory)

        self.assertEqual(captured["proxy"]["proxy_type"], "socks5")
        self.assertEqual(captured["proxy"]["addr"], "127.0.0.1")
        self.assertEqual(captured["proxy"]["port"], 18080)

    async def test_connection_is_reused(self):
        client = FakeClient()
        service = self.make_service(client)

        await service.is_authorized()
        await service.is_authorized()

        self.assertEqual(client.connected_calls, 1)

    async def test_list_folders_maps_custom_filter(self):
        client = FakeClient()
        client.filters = [
            DialogFilter(
                id=2,
                title=TextWithEntities(text="Работа", entities=[]),
                pinned_peers=[InputPeerUser(7, 0)],
                include_peers=[InputPeerUser(8, 0)],
                exclude_peers=[InputPeerChannel(10, 0)],
                contacts=True,
                groups=True,
                broadcasts=None,
                bots=None,
                exclude_muted=True,
                exclude_read=True,
                exclude_archived=True,
                emoticon="💼",
            )
        ]
        service = self.make_service(client)

        folders = await service.list_folders()

        self.assertEqual([folder.key for folder in folders], ["all", "archive", "folder:2"])
        custom = folders[2]
        self.assertEqual(custom.title, "Работа")
        self.assertEqual(custom.pinned_peers, frozenset({7}))
        self.assertEqual(custom.include_peers, frozenset({8}))
        self.assertEqual(custom.exclude_peers, frozenset({-1000000000010}))
        self.assertTrue(custom.contacts)
        self.assertTrue(custom.groups)
        self.assertTrue(custom.exclude_muted)
        self.assertTrue(custom.exclude_read)
        self.assertTrue(custom.exclude_archived)
        self.assertEqual(custom.emoticon, "💼")

    async def test_list_folders_returns_defaults_on_rpc_error(self):
        class BrokenClient(FakeClient):
            async def __call__(self, request):
                raise RPCError(None, "FILTERS_UNAVAILABLE", 500)

        service = self.make_service(BrokenClient())

        folders = await service.list_folders()

        self.assertEqual([folder.key for folder in folders], ["all", "archive"])

    async def test_list_chats_maps_users_groups_channels_and_metadata(self):
        user = User(id=7, first_name="Alex", username="alex", contact=True)
        group = FakeEntity(99, "Group chat")
        channel = FakeEntity(100, "News", username="news")
        client = FakeClient()
        client.dialogs = [
            FakeDialog(
                user,
                dialog_id=7,
                message=FakeMessage(1, 7, "hello"),
                unread=2,
                pinned=True,
                is_user=True,
            ),
            FakeDialog(
                group,
                dialog_id=-99,
                message=FakeMessage(2, -99, "group message", media="photo"),
                is_group=True,
            ),
            FakeDialog(
                channel,
                dialog_id=-1000000000100,
                message=FakeMessage(3, -1000000000100, "news"),
                is_channel=True,
                archived=True,
                muted=True,
            ),
        ]
        service = self.make_service(client)

        chats = await service.list_chats()

        self.assertEqual(len(chats), 3)
        by_id = {chat.id: chat for chat in chats}
        self.assertEqual(by_id[7].kind, "user")
        self.assertTrue(by_id[7].is_contact)
        self.assertEqual(by_id[7].unread, 2)
        self.assertTrue(by_id[7].pinned)
        self.assertEqual(by_id[7].last_message, "hello")
        self.assertEqual(by_id[-99].kind, "group")
        self.assertEqual(by_id[-99].last_message, "Фото · group message")
        self.assertEqual(by_id[-1000000000100].kind, "channel")
        self.assertTrue(by_id[-1000000000100].archived)
        self.assertTrue(by_id[-1000000000100].muted)
        self.assertEqual(client.dialog_limit, None)

    async def test_get_messages_maps_media_and_reverses_order(self):
        user = User(id=7, first_name="Alex", username="alex")
        client = FakeClient()
        client.entity = user
        client.messages = [
            FakeMessage(2, 7, "newer", out=True),
            FakeMessage(1, 7, "older", sender=User(id=7, first_name="Alex", last_name="Smith", username="alex"), media="document", reply_to=2),
        ]
        service = self.make_service(client)

        messages = await service.get_messages(7, limit=20)

        self.assertEqual([message.id for message in messages], [1, 2])
        older, newer = messages
        self.assertEqual(older.text, "older")
        self.assertEqual(older.sender_name, "Alex Smith")
        self.assertEqual(older.media, "Файл: report.pdf")
        self.assertEqual(older.reply_to, 2)
        self.assertTrue(newer.out)
        self.assertEqual(client.message_calls[0][1:], (20, 0))

    async def test_send_message_success_not_retried(self):
        user = User(id=7, first_name="Alex", username="alex")
        client = FakeClient()
        client.entity = user
        client.sent_message = FakeMessage(5, 7, "keep _underscores_", out=True)
        service = self.make_service(client)
        text = "keep _underscores_ and *stars* literally"

        outcome = await service.send_message(7, text)

        self.assertEqual(outcome.kind, "sent")
        self.assertEqual(outcome.sent_message.text, "keep _underscores_")
        self.assertEqual(client.send_calls, [(user, text, None)])
        self.assertEqual(len(client.send_calls), 1)

    async def test_send_rejects_empty_text_without_network_call(self):
        service = self.make_service(FakeClient())

        outcome = await service.send_message(7, "   ")

        self.assertEqual(outcome.kind, "failed")
        self.assertEqual(outcome.code, "empty")

    async def test_send_timeout_is_unknown_and_not_retried(self):
        client = FakeClient()
        client.entity = User(id=7, first_name="Alex")
        client.send_error = asyncio.TimeoutError()
        service = self.make_service(client)

        outcome = await service.send_message(7, "hello")

        self.assertEqual(outcome.kind, "unknown")
        self.assertEqual(outcome.code, errors.SEND_UNKNOWN)
        self.assertEqual(len(client.send_calls), 1)

    async def test_send_flood_wait_is_reported_with_seconds(self):
        client = FakeClient()
        client.entity = User(id=7, first_name="Alex")
        client.send_error = FloodWaitError(None, 12)
        service = self.make_service(client)

        outcome = await service.send_message(7, "hello")

        self.assertEqual(outcome.kind, "failed")
        self.assertEqual(outcome.code, errors.FLOOD_WAIT)
        self.assertEqual(outcome.seconds, 12)

    async def test_send_rpc_rejection_is_failed_without_raw_details(self):
        client = FakeClient()
        client.entity = User(id=7, first_name="Alex")
        client.send_error = RPCError(None, "CHAT_WRITE_FORBIDDEN_SECRET", 403)
        service = self.make_service(client)

        outcome = await service.send_message(7, "hello")

        self.assertEqual(outcome.kind, "failed")
        self.assertNotIn("SECRET", outcome.code)

    async def test_resolve_username_normalizes_optional_at(self):
        client = FakeClient()
        client.entity = User(id=7, first_name="Alex", last_name="Smith", username="alex")
        service = self.make_service(client)

        chat = await service.resolve_username("@alex")

        self.assertEqual(chat.id, 7)
        self.assertEqual(chat.title, "Alex Smith")
        self.assertEqual(chat.username, "alex")

    async def test_unresolved_username_has_safe_error(self):
        service = self.make_service(FakeClient())

        with self.assertRaises(TelegramServiceError) as error:
            await service.resolve_username("missing")

        self.assertEqual(error.exception.code, errors.USERNAME_NOT_FOUND)
        self.assertNotIn("private lookup detail", str(error.exception))

    async def test_channel_username_is_rejected(self):
        client = FakeClient()
        client.entity = FakeEntity(100, "Channel")
        service = self.make_service(client)

        with self.assertRaises(TelegramServiceError) as error:
            await service.resolve_username("channel")

        self.assertEqual(error.exception.code, errors.NOT_A_PERSON)

    async def test_login_code_flow_and_two_step_challenge(self):
        client = FakeClient()
        client.sign_in_error = SessionPasswordNeededError(None)
        service = self.make_service(client)

        await service.request_login_code("+10000000000")
        completed = await service.sign_in_code("+10000000000", "12345")

        self.assertEqual(client.phone, "+10000000000")
        self.assertFalse(completed)

    async def test_invalid_login_code_is_sanitized(self):
        client = FakeClient()
        client.sign_in_error = PhoneCodeInvalidError(None)
        service = self.make_service(client)

        with self.assertRaises(TelegramServiceError) as error:
            await service.sign_in_code("+10000000000", "12345")

        self.assertEqual(error.exception.code, errors.LOGIN_CODE_INVALID)
        self.assertNotIn("12345", str(error.exception))

    async def test_invalid_phone_is_sanitized(self):
        class PhoneClient(FakeClient):
            async def send_code_request(self, phone):
                raise PhoneNumberInvalidError(None)

        service = self.make_service(PhoneClient())

        with self.assertRaises(TelegramServiceError) as error:
            await service.request_login_code("+1")

        self.assertEqual(error.exception.code, errors.LOGIN_PHONE_INVALID)

    async def test_invalid_password_is_sanitized(self):
        client = FakeClient()
        client.sign_in_error = PasswordHashInvalidError(None)
        service = self.make_service(client)

        with self.assertRaises(TelegramServiceError) as error:
            await service.sign_in_password("secret")

        self.assertEqual(error.exception.code, errors.LOGIN_PASSWORD_INVALID)
        self.assertNotIn("secret", str(error.exception))

    async def test_get_me_returns_safe_account(self):
        service = self.make_service(FakeClient())

        account = await service.get_me()

        self.assertEqual(account.id, 7)
        self.assertEqual(account.display_name, "Alex Smith")
        self.assertEqual(account.username, "alex")

    async def test_mark_read_is_quiet(self):
        client = FakeClient()
        entity = User(id=7, first_name="Alex")
        client.entity = entity
        service = self.make_service(client)

        await service.mark_read(7)

        self.assertIs(client.read_entity, entity)


if __name__ == "__main__":
    unittest.main()
