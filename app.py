from pathlib import Path
import tkinter as tk
from tkinter import messagebox

from telegram_personal_messenger.async_worker import AsyncWorker
from telegram_personal_messenger.config import CredentialError, Settings, load_settings
from telegram_personal_messenger.telegram_service import TelegramService
from telegram_personal_messenger.ui import CredentialSetupWindow, MessengerWindow


def main() -> None:
    root = tk.Tk()
    app_dir = Path(__file__).resolve().parent
    env_path = app_dir / ".env"

    def start_messenger(settings: Settings, auto_open_login: bool) -> None:
        service = TelegramService(settings)
        worker = AsyncWorker()
        MessengerWindow(
            root,
            service,
            worker,
            auto_open_login=auto_open_login,
        )

    try:
        settings = load_settings(env_path)
    except CredentialError:
        CredentialSetupWindow(
            root,
            env_path,
            on_saved=lambda settings: start_messenger(settings, auto_open_login=True),
            on_cancel=root.destroy,
        )
    except (OSError, ValueError) as error:
        root.withdraw()
        messagebox.showerror(
            "Настройка Telegram",
            "Не удалось загрузить настройки Windows.\n\n"
            "Проверь LOCALAPPDATA и повтори запуск.\n\n"
            f"Подробность: {error}",
            parent=root,
        )
        root.destroy()
        return
    else:
        start_messenger(settings, auto_open_login=False)

    root.mainloop()


if __name__ == "__main__":
    main()
