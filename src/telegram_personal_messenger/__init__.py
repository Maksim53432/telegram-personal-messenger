"""Минимальный клиент Telegram с графическим интерфейсом."""

__version__ = "0.1.0"

# Удобные реэкспорты, чтобы можно было писать:
# from telegram_personal_messenger import TgClient, load_config
from .client import TgClient
from .config import load_config

__all__ = ["TgClient", "load_config", "__version__"]