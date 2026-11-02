from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import app as application
from telegram_personal_messenger.config import CredentialError, Settings


class AppStartupTests(unittest.TestCase):
    def setUp(self):
        self.root = Mock()
        self.settings = Settings(12345, "a" * 32, Path("session"))
        self.env_path = Path(application.__file__).resolve().parent / ".env"

    def test_missing_credentials_show_setup_without_service_or_worker(self):
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "load_settings", side_effect=CredentialError("missing")),
            patch.object(application.messagebox, "showerror"),
            patch.object(application, "CredentialSetupWindow", create=True) as setup,
            patch.object(application, "TelegramService") as service,
            patch.object(application, "AsyncWorker") as worker,
            patch.object(application, "MessengerWindow") as messenger,
        ):
            application.main()

        setup.assert_called_once()
        self.assertIs(setup.call_args.args[0], self.root)
        self.assertEqual(setup.call_args.args[1], self.env_path)
        service.assert_not_called()
        worker.assert_not_called()
        messenger.assert_not_called()
        self.root.mainloop.assert_called_once()

    def test_cancelled_setup_destroys_root_without_starting_service(self):
        def setup_side_effect(root, env_path, on_saved, on_cancel):
            on_cancel()

        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "load_settings", side_effect=CredentialError("missing")),
            patch.object(application.messagebox, "showerror"),
            patch.object(application, "CredentialSetupWindow", create=True, side_effect=setup_side_effect),
            patch.object(application, "TelegramService") as service,
            patch.object(application, "AsyncWorker") as worker,
        ):
            application.main()

        self.root.destroy.assert_called_once()
        service.assert_not_called()
        worker.assert_not_called()

    def test_saved_credentials_reload_settings_before_starting_messenger(self):
        def setup_side_effect(root, env_path, on_saved, on_cancel):
            on_saved(self.settings)

        service_instance = Mock()
        worker_instance = Mock()
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "load_settings", side_effect=CredentialError("missing")),
            patch.object(application.messagebox, "showerror"),
            patch.object(application, "CredentialSetupWindow", create=True, side_effect=setup_side_effect),
            patch.object(application, "TelegramService", return_value=service_instance) as service,
            patch.object(application, "AsyncWorker", return_value=worker_instance) as worker,
            patch.object(application, "MessengerWindow") as messenger,
        ):
            application.main()

        service.assert_called_once_with(self.settings)
        worker.assert_called_once_with()
        messenger.assert_called_once_with(
            self.root,
            service_instance,
            worker_instance,
            auto_open_login=True,
        )
        self.root.mainloop.assert_called_once()

    def test_valid_existing_configuration_keeps_normal_startup(self):
        service_instance = Mock()
        worker_instance = Mock()
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "load_settings", return_value=self.settings),
            patch.object(application, "CredentialSetupWindow", create=True) as setup,
            patch.object(application, "TelegramService", return_value=service_instance),
            patch.object(application, "AsyncWorker", return_value=worker_instance),
            patch.object(application, "MessengerWindow") as messenger,
        ):
            application.main()

        setup.assert_not_called()
        messenger.assert_called_once_with(
            self.root,
            service_instance,
            worker_instance,
            auto_open_login=False,
        )

    def test_filesystem_settings_error_does_not_open_credential_setup(self):
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "load_settings", side_effect=OSError("disk unavailable")),
            patch.object(application, "CredentialSetupWindow", create=True) as setup,
            patch.object(application.messagebox, "showerror") as showerror,
            patch.object(application, "TelegramService") as service,
            patch.object(application, "AsyncWorker") as worker,
        ):
            application.main()

        setup.assert_not_called()
        showerror.assert_called_once()
        service.assert_not_called()
        worker.assert_not_called()
        self.root.destroy.assert_called_once()

    def test_non_credential_settings_error_does_not_open_credential_setup(self):
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "load_settings", side_effect=ValueError("LOCALAPPDATA is unavailable")),
            patch.object(application, "CredentialSetupWindow", create=True) as setup,
            patch.object(application.messagebox, "showerror") as showerror,
            patch.object(application, "TelegramService") as service,
            patch.object(application, "AsyncWorker") as worker,
        ):
            application.main()

        setup.assert_not_called()
        showerror.assert_called_once()
        service.assert_not_called()
        worker.assert_not_called()
        self.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
