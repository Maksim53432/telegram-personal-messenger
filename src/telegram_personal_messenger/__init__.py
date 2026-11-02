"""Личный клиент Telegram с графическим интерфейсом."""

from .config import Settings, load_settings
from .models import Chat, Folder, Message, SendOutcome
from .telegram_service import TelegramService

__version__ = "0.2.0"

__all__ = [
    "Chat",
    "Folder",
    "Message",
    "SendOutcome",
    "Settings",
    "TelegramService",
    "load_settings",
    "__version__",
]
