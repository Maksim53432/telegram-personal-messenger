from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import telegram_personal_messenger.config as config
from telegram_personal_messenger.config import load_settings


class ConfigTests(unittest.TestCase):
    def test_loads_valid_credentials_and_local_session_path(self):
        with TemporaryDirectory() as local_app_data:
            settings = load_settings(
                Path("unused.env"),
                {
                    "TELEGRAM_API_ID": "12345",
                    "TELEGRAM_API_HASH": "a" * 32,
                    "LOCALAPPDATA": local_app_data,
                },
            )

        self.assertEqual(settings.api_id, 12345)
        self.assertEqual(settings.api_hash, "a" * 32)
        self.assertIn("TelegramPersonalMessenger", str(settings.session_path))

    def test_accepts_uppercase_hex_api_hash_unchanged(self):
        with TemporaryDirectory() as local_app_data:
            settings = load_settings(
                Path("unused.env"),
                {
                    "TELEGRAM_API_ID": "12345",
                    "TELEGRAM_API_HASH": "ABCDEF0123456789" * 2,
                    "LOCALAPPDATA": local_app_data,
                },
            )

        self.assertEqual(settings.api_hash, "ABCDEF0123456789" * 2)

    def test_environment_credentials_override_dotenv_values(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "TELEGRAM_API_ID=11111\n"
                + "TELEGRAM_API_HASH="
                + "aabbccddeeff0011" * 2
                + "\n",
                encoding="utf-8",
            )
            settings = load_settings(
                env_path,
                {
                    "TELEGRAM_API_ID": "22222",
                    "LOCALAPPDATA": directory,
                },
            )

        self.assertEqual(settings.api_id, 22222)
        self.assertEqual(settings.api_hash, "aabbccddeeff0011" * 2)

    def test_rejects_missing_credentials_without_echoing_values(self):
        with self.assertRaisesRegex(ValueError, "TELEGRAM_API_ID") as error:
            load_settings(
                Path("unused.env"),
                {
                    "TELEGRAM_API_HASH": "do-not-print-this-secret",
                    "LOCALAPPDATA": "unused-local-app-data",
                },
            )

        self.assertNotIn("do-not-print-this-secret", str(error.exception))

    def test_rejects_non_integer_api_id(self):
        with self.assertRaisesRegex(ValueError, "must be an integer"):
            load_settings(
                Path("unused.env"),
                {
                    "TELEGRAM_API_ID": "not-an-integer",
                    "TELEGRAM_API_HASH": "a" * 32,
                    "LOCALAPPDATA": "unused-local-app-data",
                },
            )

    def test_rejects_non_positive_or_non_ascii_decimal_api_id(self):
        with TemporaryDirectory() as local_app_data:
            for api_id in ("0", "-1", "1.5", "١٢٣"):
                with self.subTest(api_id=api_id), self.assertRaises(ValueError):
                    load_settings(
                        Path("unused.env"),
                        {
                            "TELEGRAM_API_ID": api_id,
                            "TELEGRAM_API_HASH": "a" * 32,
                            "LOCALAPPDATA": local_app_data,
                        },
                    )

    def test_rejects_api_hash_with_wrong_length_or_non_hex_characters(self):
        with TemporaryDirectory() as local_app_data:
            for api_hash in ("a" * 31, "a" * 33, "g" * 32, "a" * 31 + " "):
                with self.subTest(api_hash_length=len(api_hash)), self.assertRaises(ValueError):
                    load_settings(
                        Path("unused.env"),
                        {
                            "TELEGRAM_API_ID": "12345",
                            "TELEGRAM_API_HASH": api_hash,
                            "LOCALAPPDATA": local_app_data,
                        },
                    )


class ConfigPersistenceTests(unittest.TestCase):
    def save_credentials(self):
        writer = getattr(config, "save_api_credentials", None)
        self.assertTrue(callable(writer), "config.save_api_credentials must be implemented")
        return writer

    def test_saves_credentials_and_preserves_unrelated_lines(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text("# keep this comment\nOTHER=value\n", encoding="utf-8")

            self.save_credentials()(env_path, "12345", "A" * 32, env={})

            text = env_path.read_text(encoding="utf-8")
        self.assertIn("# keep this comment", text)
        self.assertIn("OTHER=value", text)
        self.assertEqual(text.count("TELEGRAM_API_ID="), 1)
        self.assertEqual(text.count("TELEGRAM_API_HASH="), 1)
        self.assertIn("TELEGRAM_API_ID=12345", text)
        self.assertIn(f"TELEGRAM_API_HASH={'A' * 32}", text)

    def test_replaces_duplicate_credentials_once(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "# first\nTELEGRAM_API_ID=1\nKEEP=yes\nTELEGRAM_API_ID=2\n"
                "TELEGRAM_API_HASH=old\nTELEGRAM_API_HASH=older\n",
                encoding="utf-8",
            )

            self.save_credentials()(env_path, "12345", "b" * 32, env={})

            text = env_path.read_text(encoding="utf-8")
        self.assertEqual(text.count("TELEGRAM_API_ID="), 1)
        self.assertEqual(text.count("TELEGRAM_API_HASH="), 1)
        self.assertIn("# first", text)
        self.assertIn("KEEP=yes", text)
        self.assertIn("TELEGRAM_API_ID=12345", text)
        self.assertIn(f"TELEGRAM_API_HASH={'b' * 32}", text)

    def test_replace_failure_preserves_old_file_and_hides_secret(self):
        secret = "c" * 32
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            original = "KEEP=unchanged\n"
            env_path.write_text(original, encoding="utf-8")

            with patch.object(config.os, "replace", side_effect=OSError(secret)):
                with self.assertRaises(ValueError) as error:
                    self.save_credentials()(env_path, "12345", secret, env={})

            self.assertEqual(env_path.read_text(encoding="utf-8"), original)
            self.assertNotIn(secret, str(error.exception))

    def test_unreadable_env_file_is_preserved_and_reports_safe_error(self):
        secret = "e" * 32
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            original = bytes((0xFF, 0xFE))
            env_path.write_bytes(original)

            with self.assertRaises(config.CredentialError) as error:
                self.save_credentials()(env_path, "12345", secret, env={})

            self.assertEqual(env_path.read_bytes(), original)
            self.assertNotIn(secret, str(error.exception))

    def test_environment_override_must_match_saved_value(self):
        secret = "d" * 32
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            with self.assertRaises(ValueError) as error:
                self.save_credentials()(
                    env_path,
                    "12345",
                    secret,
                    env={"TELEGRAM_API_ID": "99999"},
                )
            self.assertFalse(env_path.exists())
            self.assertNotIn(secret, str(error.exception))


if __name__ == "__main__":
    unittest.main()


class LegacyAndSessionConfigTests(unittest.TestCase):
    def test_reads_legacy_tg_credentials_and_session(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "TG_API_ID=12345\n"
                f"TG_API_HASH={'a' * 32}\n"
                "TG_SESSION=old-session\n",
                encoding="utf-8",
            )
            settings = load_settings(env_path, {"LOCALAPPDATA": directory})

        self.assertEqual(settings.api_id, 12345)
        self.assertEqual(settings.api_hash, "a" * 32)
        self.assertEqual(settings.session_string, "old-session")

    def test_save_session_string_replaces_old_value_and_preserves_others(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "KEEP=yes\nTG_SESSION=old\nTELEGRAM_API_ID=1\n",
                encoding="utf-8",
            )

            config.save_session_string(env_path, "new-session")

            text = env_path.read_text(encoding="utf-8")
        self.assertIn("KEEP=yes", text)
        self.assertEqual(text.count("TG_SESSION="), 1)
        self.assertIn("TG_SESSION=new-session", text)
        self.assertNotIn("TG_SESSION=old", text)

    def test_save_api_credentials_removes_legacy_api_lines(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "TG_API_ID=1\nTG_API_HASH=old\nTG_SESSION=keep\n",
                encoding="utf-8",
            )

            config.save_api_credentials(env_path, "12345", "b" * 32, env={})

            text = env_path.read_text(encoding="utf-8")
        self.assertNotIn("TG_API_ID=", text)
        self.assertNotIn("TG_API_HASH=", text)
        self.assertIn("TG_SESSION=keep", text)
        self.assertIn("TELEGRAM_API_ID=12345", text)

    def test_session_path_uses_xdg_when_localappdata_missing(self):
        settings = load_settings(
            Path("unused.env"),
            {
                "TELEGRAM_API_ID": "12345",
                "TELEGRAM_API_HASH": "a" * 32,
                "XDG_DATA_HOME": "/tmp/xdg-data",
            },
        )
        self.assertEqual(
            settings.session_path,
            Path("/tmp/xdg-data") / "TelegramPersonalMessenger" / "session",
        )


class ProxyConfigTests(unittest.TestCase):
    def test_load_settings_reads_proxy(self):
        with TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env"
            env_path.write_text(
                "TELEGRAM_API_ID=12345\n"
                f"TELEGRAM_API_HASH={'a' * 32}\n"
                "TG_PROXY=socks5://127.0.0.1:18080\n",
                encoding="utf-8",
            )
            settings = load_settings(env_path, {"LOCALAPPDATA": directory})

        self.assertIsNotNone(settings.proxy)
        self.assertEqual(settings.proxy.kind, "socks5")
        self.assertEqual(settings.proxy.host, "127.0.0.1")
        self.assertEqual(settings.proxy.port, 18080)
        self.assertEqual(
            settings.proxy.as_telethon()["proxy_type"],
            "socks5",
        )

    def test_socks5h_and_http_with_credentials(self):
        socks = config.parse_proxy("socks5h://user:pa%20ss@localhost:1080")
        self.assertEqual(socks.kind, "socks5")
        self.assertEqual(socks.username, "user")
        self.assertEqual(socks.password, "pa ss")
        self.assertTrue(socks.rdns)

        http = config.parse_proxy("http://127.0.0.1:8080")
        self.assertEqual(http.kind, "http")
        self.assertEqual(http.port, 8080)

    def test_invalid_proxy_does_not_echo_secret(self):
        with self.assertRaises(config.CredentialError) as error:
            config.parse_proxy("ftp://user:super-secret@127.0.0.1:21")
        self.assertNotIn("super-secret", str(error.exception))

    def test_empty_proxy_is_none(self):
        self.assertIsNone(config.parse_proxy("  "))
