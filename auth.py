"""QR-вход и обработка 2FA со скрытым вводом пароля."""
import asyncio
import getpass
import logging

from telethon import TelegramClient
from telethon.errors import (
    PasswordHashInvalidError,
    SessionPasswordNeededError,
)

logger = logging.getLogger(__name__)

MAX_2FA_ATTEMPTS = 3


async def ask_2fa(client: TelegramClient) -> None:
    """
    Запрашивает пароль 2FA со скрытым вводом.
    Повторяет при неверном пароле до MAX_2FA_ATTEMPTS раз.
    """
    logger.info("Аккаунт защищён 2FA. Пароль не будет отображаться при вводе.")
    for attempt in range(1, MAX_2FA_ATTEMPTS + 1):
        try:
            password = getpass.getpass(
                f"Пароль 2FA (попытка {attempt}/{MAX_2FA_ATTEMPTS}, ввод скрыт): "
            )
        except (EOFError, KeyboardInterrupt):
            logger.error("Ввод пароля прерван")
            raise

        if not password:
            logger.warning("Пустой пароль")
            continue

        try:
            await client.sign_in(password=password)
            logger.info("2FA пройдена успешно")
            return
        except PasswordHashInvalidError:
            logger.warning("Неверный пароль 2FA")
        except SessionPasswordNeededError:
            logger.warning("Пароль не принят, попробуй ещё раз")

    raise SystemExit(f"{MAX_2FA_ATTEMPTS} неверных попытки ввода 2FA.")


async def qr_login(client: TelegramClient) -> None:
    """Вход по QR-коду. Не требует цифрового кода из Telegram."""
    logger.info("Запускаю QR-вход...")
    qr = await client.qr_login()

    try:
        import qrcode
        qr_obj = qrcode.QRCode(border=1)
        qr_obj.add_data(qr.url)
        qr_obj.make(fit=True)
        qr_obj.print_ascii(invert=True)
        logger.info(
            "Отсканируй QR в Telegram: Настройки → Устройства → Подключить устройство"
        )
    except ImportError:
        logger.warning("Модуль qrcode не установлен. Открой ссылку вручную:")
        print(f"\n{qr.url}\n")

    try:
        await qr.wait(timeout=120)
        logger.info("QR-вход подтверждён")
    except asyncio.TimeoutError:
        logger.error("QR-код истёк (120 сек). Перезапусти.")
        raise
    except SessionPasswordNeededError:
        await ask_2fa(client)