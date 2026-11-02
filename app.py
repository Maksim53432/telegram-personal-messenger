#!/usr/bin/env python3
"""Минимальный консольный клиент Telegram."""
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Добавляем src в путь, чтобы импортировать пакет
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from telegram_personal_messenger.auth import qr_login  # noqa: E402
from telegram_personal_messenger.client import TgClient  # noqa: E402
from telegram_personal_messenger.config import load_config  # noqa: E402

# ─── Логирование ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("telethon.network").setLevel(logging.INFO)
logging.getLogger("telethon.extensions").setLevel(logging.INFO)
logger = logging.getLogger("app")


def update_env_session(new_session: str) -> None:
    """Обновляет TG_SESSION в .env, чтобы не логиниться каждый раз."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        logger.warning(".env не найден, сессию сохрани вручную")
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []
    found = False
    for line in lines:
        if line.startswith("TG_SESSION="):
            new_lines.append(f"TG_SESSION={new_session}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"TG_SESSION={new_session}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    logger.info("Сессия обновлена в .env")


async def on_incoming(event) -> None:
    sender = await event.get_sender()
    name = getattr(sender, "first_name", None) or getattr(sender, "title", "?")
    print(f"\n[{name}]: {event.raw_text}")


async def main() -> None:
    api_id, api_hash, session_str = load_config()
    tg = TgClient(api_id, api_hash, session_str)

    new_session = await tg.connect_and_auth()
    if new_session and new_session != session_str:
        update_env_session(new_session)

    me = await tg.get_me()
    print(f"\n✅ Залогинен как: {me.first_name} (@{me.username}) id={me.id}\n")

    # Тестовое сообщение
    await tg.send_to_saved("Тест из консольного клиента на сервере 👋")

    tg.start_listening(on_incoming)
    print("Слушаю входящие. Ctrl+C для выхода.\n")

    try:
        await tg.run_until_disconnected()
    finally:
        await tg.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nВыход.")