from pathlib import Path
import unittest
from unittest.mock import Mock, patch

import app as application
from telegram_personal_messenger.config import CredentialError, Settings


class AppStartupTests(unittest.TestCase):
    def setUp(self):
        self.root = Mock()
        self.root.winfo_children.return_value = []
        self.theme = Mock()
        self.settings = Settings(12345, "a" * 32, Path("session"))
        self.env_path = Path(application.__file__).resolve().parent / ".env"

    def test_missing_credentials_show_setup_without_starting_client(self):
        setup = Mock()
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "Theme", return_value=self.theme),
            patch.object(application, "load_settings", side_effect=CredentialError("missing")),
            patch.object(application, "SetupView", return_value=setup) as setup_class,
            patch.object(application, "_create_app") as create,
        ):
            application.main()

        setup_class.assert_called_once()
        self.assertIs(setup_class.call_args.args[0], self.root)
        self.assertIs(setup_class.call_args.args[1], self.theme)
        self.assertEqual(setup_class.call_args.args[2], self.env_path)
        setup.pack.assert_called_once_with(fill="both", expand=True)
        create.assert_not_called()
        self.root.mainloop.assert_called_once()

    def test_cancelled_setup_destroys_root_without_starting_client(self):
        def setup_side_effect(_root, _theme, _env_path, _on_saved, on_cancel):
            on_cancel()
            return Mock()

        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "Theme", return_value=self.theme),
            patch.object(application, "load_settings", side_effect=CredentialError("missing")),
            patch.object(application, "SetupView", side_effect=setup_side_effect),
            patch.object(application, "_create_app") as create,
        ):
            application.main()

        self.root.destroy.assert_called_once()
        create.assert_not_called()

    def test_saved_credentials_start_the_client(self):
        def setup_side_effect(_root, _theme, _env_path, on_saved, _on_cancel):
            on_saved(self.settings)
            return Mock()

        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "Theme", return_value=self.theme),
            patch.object(application, "load_settings", side_effect=CredentialError("missing")),
            patch.object(application, "SetupView", side_effect=setup_side_effect),
            patch.object(application, "_create_app") as create,
        ):
            application.main()

        create.assert_called_once_with(self.root, self.theme, self.settings, self.env_path)

    def test_valid_configuration_starts_the_client(self):
        app = Mock()
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "Theme", return_value=self.theme),
            patch.object(application, "load_settings", return_value=self.settings),
            patch.object(application, "SetupView") as setup,
            patch.object(application, "_create_app", return_value=app) as create,
        ):
            application.main()

        setup.assert_not_called()
        create.assert_called_once_with(self.root, self.theme, self.settings, self.env_path)
        self.root.mainloop.assert_called_once()

    def test_settings_filesystem_error_shows_message_and_does_not_open_setup(self):
        with (
            patch.object(application.tk, "Tk", return_value=self.root),
            patch.object(application, "Theme", return_value=self.theme),
            patch.object(application, "load_settings", side_effect=OSError("disk unavailable")),
            patch.object(application, "SetupView") as setup,
            patch.object(application.messagebox, "showerror") as showerror,
            patch.object(application, "_create_app") as create,
        ):
            application.main()

        setup.assert_not_called()
        showerror.assert_called_once()
        create.assert_not_called()
        self.root.destroy.assert_called_once()


class CreateAppTests(unittest.TestCase):
    def setUp(self):
        self.root = Mock()
        self.root.winfo_children.return_value = []
        self.theme = Mock()
        self.settings = Settings(12345, "a" * 32, Path("session"))
        self.env_path = Path("unused.env")

    def test_creates_worker_service_and_window(self):
        worker = Mock()
        service = Mock()
        window = Mock()
        with (
            patch.object(application, "AsyncWorker", return_value=worker),
            patch.object(application, "TelegramService", return_value=service) as service_class,
            patch.object(application, "MainWindow", return_value=window) as window_class,
        ):
            result = application._create_app(
                self.root,
                self.theme,
                self.settings,
                self.env_path,
            )

        service_class.assert_called_once_with(self.settings)
        window_class.assert_called_once_with(
            self.root,
            self.theme,
            service,
            worker,
            self.settings,
            self.env_path,
        )
        self.assertIs(result, window)
        self.assertIs(self.root._telegram_app, window)

    def test_service_failure_closes_worker_and_shows_error(self):
        worker = Mock()
        with (
            patch.object(application, "AsyncWorker", return_value=worker),
            patch.object(application, "TelegramService", side_effect=RuntimeError("private details")),
            patch.object(application.messagebox, "showerror") as showerror,
            patch.object(application, "MainWindow") as window,
        ):
            result = application._create_app(
                self.root,
                self.theme,
                self.settings,
                self.env_path,
            )

        self.assertIsNone(result)
        worker.close.assert_called_once()
        showerror.assert_called_once()
        self.assertNotIn("private details", showerror.call_args.args[1])
        window.assert_not_called()
        self.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
