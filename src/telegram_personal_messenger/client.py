"""Обёртка над Telethon для GUI."""
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .auth import qr_login

logger = logging.getLogger(__name__)


class TgClient:
    def __init__(self, api_id: int, api_hash: str, session_str: str = ""):
        self.client = TelegramClient(StringSession(session_str), api_id, api_hash)

    async def connect_and_auth(self) -> str:
        logger.info("Подключаюсь...")
        await self.client.connect()
        if not await self.client.is_user_authorized():
            logger.info("Нужен вход, запускаю QR")
            await qr_login(self.client)
        return self.client.session.save()

    async def get_me(self):
        return await self.client.get_me()

    def start_listening(self, callback) -> None:
        @self.client.on(events.NewMessage(incoming=True))
        async def _handler(event):
            await callback(event)
        logger.info("Слушаю входящие...")

    async def disconnect(self):
        await self.client.disconnect()