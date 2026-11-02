#!/usr/bin/env python3
"""Запуск графического клиента Telegram."""
import asyncio
import logging
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from telegram_personal_messenger.config import load_config
from telegram_personal_messenger.client import TgClient
from telegram_personal_messenger.gui import TgGui

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("app")


def update_env_session(new_session: str) -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text().splitlines()
    out = []
    found = False
    for line in lines:
        if line.startswith("TG_SESSION="):
            out.append(f"TG_SESSION={new_session}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"TG_SESSION={new_session}")
    env_path.write_text("\n".join(out) + "\n")


def start_background_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


async def async_main(tg: TgClient):
    new_session = await tg.connect_and_auth()
    if new_session:
        update_env_session(new_session)
    me = await tg.get_me()
    logger.info("Вход выполнен: %s (@%s)", me.first_name, me.username)


def main() -> None:
    api_id, api_hash, session_str = load_config()

    # Отдельный поток с asyncio loop для Telethon
    loop = asyncio.new_event_loop()
    threading.Thread(target=start_background_loop, args=(loop,), daemon=True).start()

    tg = TgClient(api_id, api_hash, session_str)

    # Авторизация до запуска GUI
    future = asyncio.run_coroutine_threadsafe(async_main(tg), loop)
    future.result()  # ждём завершения входа

    # Создаём GUI в главном потоке
    gui = TgGui(tg, loop)

    # Регистрируем обработчик входящих, который пушит в GUI
    async def on_incoming(event):
        sender = await event.get_sender()
        name = getattr(sender, "first_name", None) or getattr(sender, "title", "?")
        gui.push_incoming(name, event.raw_text or "<медиа>", event.chat_id)

    tg.start_listening(on_incoming)

    # Загружаем чаты и запускаем mainloop
    gui.load_chats()
    gui.run()


if __name__ == "__main__":
    main()