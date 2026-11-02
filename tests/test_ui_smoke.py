import os
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
import unittest
from unittest.mock import Mock

from telegram_personal_messenger.config import save_api_credentials
from telegram_personal_messenger.ui import LoginView, SetupView, Theme


@unittest.skipUnless(
    os.name == "nt" or os.environ.get("DISPLAY"),
    "нужен графический дисплей",
)
class TkWidgetSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(f"Tkinter недоступен: {error}")
        self.root.withdraw()
        self.theme = Theme(self.root)

    def tearDown(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_login_view_can_be_built_and_switched_to_password_step(self):
        view = LoginView(
            self.root,
            self.theme,
            Mock(),
            lambda _coro, _ok, _error: None,
            lambda: None,
        )
        view.pack(fill="both", expand=True)
        self.root.update_idletasks()

        view._show_step("code")
        view._show_step("password")
        self.root.update_idletasks()

        self.assertTrue(view.winfo_exists())
        self.assertEqual(view._step, "password")
        view.destroy()

    def test_setup_view_can_be_built_with_prefilled_credentials(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            save_api_credentials(env_path, "12345", "a" * 32, env={})
            view = SetupView(
                self.root,
                self.theme,
                env_path,
                lambda _settings: None,
                lambda: None,
            )
            view.pack(fill="both", expand=True)
            self.root.update_idletasks()

            self.assertEqual(view.api_id_entry.get(), "12345")
            self.assertEqual(view.api_hash_entry.get(), "a" * 32)
            view.destroy()
