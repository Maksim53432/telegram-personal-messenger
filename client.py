"""Обёртка над Telethon: подключение, отправка, прослушивание."""
import asyncio
import logging

from telethon import TelegramClient, events
from telethon.sessions import StringSession

from .auth import qr_login

logger = logging.getLogger(__name__)


class TgClient:
    def __init__(self, api_id: int, api_hash: str, session_str: str = ""):
        self.client = TelegramClient(StringSession(session_str), api_id, api_hash)
        self._incoming_handler = None

    async def connect_and_auth(self) -> str:
        """
        Подключается и авторизуется, если нужно.
        Возвращает актуальную строку сессии (может быть новой после QR-входа).
        """
        logger.info("Подключаюсь к серверам Telegram...")
        await self.client.connect()
        logger.info(
            "Соединение установлено. Авторизован: %s",
            await self.client.is_user_authorized(),
        )

        if not await self.client.is_user_authorized():
            logger.info("Сессии нет, запускаю QR-вход")
            await qr_login(self.client)
            new_session = self.client.session.save()
            logger.info("Новая сессия получена (сохрани в .env как TG_SESSION)")
            return new_session

        logger.info("Сессия уже была, вход не требуется")
        return self.client.session.save()

    async def get_me(self):
        return await self.client.get_me()

    async def send_to_saved(self, text: str) -> None:
        await self.client.send_message("me", text)
        logger.info("Сообщение отправлено в Saved Messages")

    def start_listening(self, on_message) -> None:
        """Регистрирует обработчик входящих сообщений."""
        @self.client.on(events.NewMessage(incoming=True))
        async def _handler(event):
            await on_message(event)

        self._incoming_handler = _handler
        logger.info("Слушаю входящие сообщения...")

    async def run_until_disconnected(self) -> None:
        await self.client.run_until_disconnected()

    async def disconnect(self) -> None:
        await self.client.disconnect()