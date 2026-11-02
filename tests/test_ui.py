from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from telegram_personal_messenger.models import Recipient
import telegram_personal_messenger.ui as ui
from telegram_personal_messenger.config import CredentialError, Settings
from telegram_personal_messenger.ui import LoginWindow, MessengerWindow, recipient_label, status_message


class UiPresentationTests(unittest.TestCase):
    def test_recipient_label_shows_username_when_available(self):
        self.assertEqual(recipient_label(Recipient(7, "Alex", "alex")), "Alex (@alex)")
        self.assertEqual(recipient_label(Recipient(8, "No username", None)), "No username")

    def test_send_statuses_are_clear_russian_copy(self):
        self.assertEqual(status_message("sending", ""), "Отправляю…")
        self.assertEqual(status_message("sent", ""), "Сообщение отправлено.")
        self.assertIn("не повторяло", status_message("unknown", ""))
        self.assertEqual(
            status_message("failed", "Enter a message before sending."),
            "Сначала введи текст сообщения.",
        )


class LoginWindowTests(unittest.TestCase):
    def make_app(self):
        app = MessengerWindow.__new__(MessengerWindow)
        app.root = Mock()
        app.service = Mock()
        app.worker = Mock()
        app.login_button = Mock()
        app.connection_label = Mock()
        app.main_frame = Mock()
        app.phone_entry = Mock()
        app._set_status = Mock()
        app._show_message_form = Mock()
        app._load_recipients = Mock()
        app._login_window = None
        app._auto_open_login = False
        return app

    def test_unauthorized_state_shows_login_button(self):
        app = self.make_app()

        app._on_authorization_checked(False)

        app.login_button.grid.assert_called_once()
        app.main_frame.grid_remove.assert_called_once()

    def test_first_run_auto_opens_login_after_authorization_check(self):
        app = self.make_app()
        app._auto_open_login = True
        app._open_login_window = Mock()

        app._on_authorization_checked(False)

        app._open_login_window.assert_called_once()
        self.assertFalse(app._auto_open_login)

    def test_opening_login_creates_a_window_when_none_exists(self):
        app = self.make_app()
        open_login = getattr(app, "_open_login_window", None)
        self.assertTrue(callable(open_login), "MessengerWindow needs a login-window action")

        with patch("telegram_personal_messenger.ui.LoginWindow") as login_window:
            created = login_window.return_value
            open_login()

        login_window.assert_called_once_with(app)
        self.assertIs(app._login_window, created)

    def test_opening_login_reuses_the_existing_window(self):
        app = self.make_app()
        existing = Mock()
        existing.winfo_exists.return_value = True
        app._login_window = existing
        open_login = getattr(app, "_open_login_window", None)
        self.assertTrue(callable(open_login), "MessengerWindow needs a login-window action")

        with patch("telegram_personal_messenger.ui.LoginWindow") as login_window:
            open_login()

        login_window.assert_not_called()
        existing.lift.assert_called_once()

    def test_successful_login_shows_message_form_and_loads_recipients(self):
        app = self.make_app()
        del app._show_message_form
        app._set_status = Mock()
        on_login_success = getattr(app, "_on_login_success", None)
        self.assertTrue(callable(on_login_success), "MessengerWindow needs a login-success callback")

        on_login_success()

        app.login_button.grid_remove.assert_called_once()
        app.main_frame.grid.assert_called_once()
        app._load_recipients.assert_called_once()


class LoginFlowTests(unittest.TestCase):
    def make_login_window(self):
        login = LoginWindow.__new__(LoginWindow)
        login.app = Mock()
        login.window = Mock()
        login.window.winfo_exists.return_value = True
        login._closed = False
        login._pending = False
        login.phone_entry = Mock()
        login.phone_entry.get.return_value = "+15550000"
        login.code_entry = Mock()
        login.password_entry = Mock()
        login.code_frame = Mock()
        login.password_frame = Mock()
        login.sign_in_button = Mock()
        login.password_button = Mock()
        login.request_code_button = Mock()
        login.cancel_button = Mock()
        login.status_label = Mock()
        login.app.service.request_login_code.return_value = object()
        login.app.service.sign_in_code.return_value = object()
        login.app.service.sign_in_password.return_value = object()
        login.app._submit.side_effect = lambda operation, on_success, _on_error: on_success(None)
        return login

    def test_requesting_code_uses_phone_and_reveals_code_field(self):
        login = self.make_login_window()
        login.phone_entry.get.return_value = " +15550000 "

        login._request_login_code()

        login.app.service.request_login_code.assert_called_once_with("+15550000")
        login.code_frame.grid.assert_called_once()
        login.sign_in_button.pack.assert_called_once()

    def test_two_step_challenge_reveals_password_field(self):
        login = self.make_login_window()
        login.code_entry.get.return_value = "12345"
        login.app._submit.side_effect = (
            lambda operation, on_success, _on_error: on_success("password_required")
        )

        login._sign_in_code()

        login.app.service.sign_in_code.assert_called_once_with("+15550000", "12345")
        login.password_frame.grid.assert_called_once()
        login.password_button.pack.assert_called_once()

    def test_successful_code_login_closes_window_and_notifies_main_window(self):
        login = self.make_login_window()
        login.code_entry.get.return_value = "12345"
        login.app._submit.side_effect = (
            lambda operation, on_success, _on_error: on_success("authenticated")
        )

        login._sign_in_code()

        self.assertTrue(login._closed)
        login.app._on_login_window_closed.assert_called_once_with(login)
        login.app._on_login_success.assert_called_once()

    def test_successful_two_step_login_notifies_main_window(self):
        login = self.make_login_window()
        login.password_entry.get.return_value = "fake-2fa-value"

        login._sign_in_password()

        login.app.service.sign_in_password.assert_called_once_with("fake-2fa-value")
        login.app._on_login_success.assert_called_once()

    def test_authentication_error_is_shown_without_raw_details(self):
        login = self.make_login_window()
        login.code_entry.get.return_value = "12345"
        login.app._translate_error.return_value = "Код не подошёл."
        login.app._submit.side_effect = (
            lambda operation, _on_success, on_error: on_error(
                RuntimeError("raw Telegram details")
            )
        )

        login._sign_in_code()

        login.app._translate_error.assert_called_once()
        login.code_entry.delete.assert_called_with(0, "end")
        self.assertEqual(login.status_label.configure.call_args.kwargs["text"], "Код не подошёл.")

    def test_cancel_during_request_does_not_destroy_window(self):
        login = self.make_login_window()
        login._pending = True

        login.close()

        login.window.destroy.assert_not_called()
        login.status_label.configure.assert_called_once()

    def test_late_callback_after_close_does_not_update_widgets(self):
        login = self.make_login_window()
        callback = Mock()
        login.destroy()

        login._on_operation_success(None, callback)

        callback.assert_not_called()
        login.status_label.configure.assert_not_called()


class CredentialSetupWindowTests(unittest.TestCase):
    def make_window(self):
        setup_class = getattr(ui, "CredentialSetupWindow", None)
        self.assertTrue(callable(setup_class), "CredentialSetupWindow must be implemented")
        setup = setup_class.__new__(setup_class)
        setup.env_path = Path("unused.env")
        setup.root = Mock()
        setup._escape_binding = None
        setup.api_id_entry = Mock()
        setup.api_id_entry.get.return_value = "12345"
        setup.api_hash_entry = Mock()
        setup.api_hash_entry.get.return_value = "a" * 32
        setup.show_hash_var = Mock()
        setup.save_button = Mock()
        setup.cancel_button = Mock()
        setup.status_label = Mock()
        setup.header = Mock()
        setup.frame = Mock()
        setup.on_saved = Mock()
        setup.on_cancel = Mock()
        setup._saving = False
        return setup

    def test_prefill_uses_effective_saved_credentials(self):
        setup = self.make_window()
        with (
            patch.object(ui, "read_api_credentials", return_value=("12345", "A" * 32)),
            patch.object(setup, "_refresh_save_button"),
        ):
            setup._prefill()

        setup.api_id_entry.insert.assert_called_once_with(0, "12345")
        setup.api_hash_entry.insert.assert_called_once_with(0, "A" * 32)

    def test_hash_toggle_masks_by_default_and_can_reveal(self):
        setup = self.make_window()
        setup.show_hash_var.get.return_value = True

        setup._toggle_hash()

        setup.api_hash_entry.configure.assert_called_once_with(show="")

    def test_extremely_long_api_id_keeps_save_disabled(self):
        setup = self.make_window()
        setup.api_id_entry.get.return_value = "9" * 5000
        setup.api_hash_entry.get.return_value = "a" * 32

        setup._refresh_save_button()

        setup.save_button.configure.assert_called_once_with(state="disabled")

    def test_save_error_keeps_values_and_does_not_continue(self):
        setup = self.make_window()
        setup.api_id_entry.get.return_value = "12345"
        setup.api_hash_entry.get.return_value = "a" * 32
        with patch.object(ui, "save_api_credentials", side_effect=CredentialError("safe error")):
            setup._save()

        setup.api_id_entry.delete.assert_not_called()
        setup.api_hash_entry.delete.assert_not_called()
        setup.on_saved.assert_not_called()
        self.assertEqual(
            setup.status_label.configure.call_args.kwargs["text"],
            "Не удалось сохранить настройки. Проверь права на папку проекта.",
        )

    def test_successful_save_continues_with_reloaded_settings(self):
        setup = self.make_window()
        setup.api_id_entry.get.return_value = "12345"
        setup.api_hash_entry.get.return_value = "a" * 32
        settings = Settings(12345, "a" * 32, Path("session"))
        with (
            patch.object(ui, "save_api_credentials") as save,
            patch.object(ui, "load_settings", return_value=settings),
        ):
            setup._save()

        save.assert_called_once_with(setup.env_path, "12345", "a" * 32)
        setup.on_saved.assert_called_once_with(settings)
        setup.header.destroy.assert_called_once()
        setup.frame.destroy.assert_called_once()

    def test_cancel_clears_fields_and_calls_cancel_callback(self):
        setup = self.make_window()
        setup.api_id_entry.delete = Mock()
        setup.api_hash_entry.delete = Mock()

        setup._cancel()

        setup.api_id_entry.delete.assert_called_once_with(0, "end")
        setup.api_hash_entry.delete.assert_called_once_with(0, "end")
        setup.header.destroy.assert_called_once()
        setup.frame.destroy.assert_called_once()
        setup.on_cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
