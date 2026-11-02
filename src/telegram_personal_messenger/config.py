"""Настройки приложения и безопасная работа с локальным .env.

В файле хранятся только API-ключи приложения. Телефон, код входа, пароль
двухэтапной проверки и текст сообщений сюда не попадают.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from string import hexdigits
from typing import Any, Literal, Mapping
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

API_ID_KEYS = ("TELEGRAM_API_ID", "TG_API_ID")
API_HASH_KEYS = ("TELEGRAM_API_HASH", "TG_API_HASH")
SESSION_KEYS = ("TG_SESSION", "TELEGRAM_SESSION")
PROXY_KEYS = ("TELEGRAM_PROXY", "TG_PROXY")
SESSION_DIR_NAME = "TelegramPersonalMessenger"

_CREDENTIALS_HINT = (
    "Укажи TELEGRAM_API_ID и TELEGRAM_API_HASH в .env. "
    "Ключи выдаются на https://my.telegram.org/apps"
)


class CredentialError(ValueError):
    """Настройки отсутствуют или имеют неверный формат."""


@dataclass(frozen=True, slots=True)
class Proxy:
    """Локальный SOCKS/HTTP-прокси для MTProto."""

    kind: Literal["socks5", "socks4", "http"]
    host: str
    port: int
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    rdns: bool = True

    def as_telethon(self) -> dict[str, Any]:
        return {
            "proxy_type": self.kind,
            "addr": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "rdns": self.rdns,
        }


@dataclass(frozen=True, slots=True)
class Settings:
    """Проверенные настройки подключения к Telegram."""

    api_id: int
    api_hash: str = field(repr=False)
    session_path: Path
    session_string: str = field(default="", repr=False)
    proxy: Proxy | None = field(default=None, repr=False)


def default_env_path() -> Path:
    """Путь к .env в корне проекта."""
    return Path(__file__).resolve().parents[2] / ".env"


def load_settings(
    env_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Settings:
    """Читает настройки из .env и окружения.

    Значения из ``env`` (или ``os.environ``, если ``env`` не передан) имеют
    приоритет над файлом. Файл при этом нужен для ключей, которых нет
    в окружении. Секреты не попадают в тексты ошибок.
    """

    path = Path(env_path) if env_path is not None else default_env_path()
    values = _merged_values(path, env)

    api_id_raw = _first(values, API_ID_KEYS)
    api_hash_raw = _first(values, API_HASH_KEYS)
    if not api_id_raw or not api_hash_raw:
        raise CredentialError(_CREDENTIALS_HINT)

    api_id, api_hash = validate_api_credentials(api_id_raw, api_hash_raw)
    session_string = (_first(values, SESSION_KEYS) or "").strip()
    proxy = parse_proxy(_first(values, PROXY_KEYS) or "")

    return Settings(
        api_id=api_id,
        api_hash=api_hash,
        session_path=session_path(values),
        session_string=session_string,
        proxy=proxy,
    )


def read_api_credentials(
    env_path: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    """Возвращает введённые ранее API ID и API Hash (без проверки)."""
    values = _merged_values(Path(env_path), env)
    return (
        _first(values, API_ID_KEYS) or "",
        _first(values, API_HASH_KEYS) or "",
    )


def parse_proxy(value: str) -> Proxy | None:
    """Разбирает socks5://, socks5h://, socks4:// или http:// URL.

    Секреты не попадают в текст ошибки.
    """

    text = value.strip()
    if not text:
        return None
    if "://" not in text:
        text = "socks5://" + text

    parsed = urlsplit(text)
    kind = parsed.scheme.lower()
    if kind == "socks5h":
        kind = "socks5"
    if kind not in ("socks5", "socks4", "http"):
        raise CredentialError(
            "TG_PROXY должен начинаться с socks5://, socks5h://, socks4:// или http://."
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise CredentialError("В TG_PROXY указан неверный порт.") from exc
    if not parsed.hostname or not port or not (1 <= port <= 65535):
        raise CredentialError(
            "TG_PROXY должен быть в формате socks5://127.0.0.1:1080."
        )

    return Proxy(
        kind=kind,
        host=parsed.hostname,
        port=port,
        username=unquote(parsed.username) if parsed.username else None,
        password=unquote(parsed.password) if parsed.password else None,
        rdns=True,
    )


def validate_api_credentials(api_id: str, api_hash: str) -> tuple[int, str]:
    """Проверяет формат API-ключей и возвращает нормализованную пару."""

    api_id_text = str(api_id).strip()
    api_hash_text = str(api_hash).strip()

    if not api_id_text.isascii() or not api_id_text.isdecimal() or int(api_id_text) <= 0:
        raise CredentialError("TELEGRAM_API_ID must be an integer greater than zero.")
    if len(api_hash_text) != 32 or any(char not in hexdigits for char in api_hash_text):
        raise CredentialError("TELEGRAM_API_HASH must be 32 hexadecimal characters.")

    return int(api_id_text), api_hash_text


def save_api_credentials(
    env_path: Path,
    api_id: str,
    api_hash: str,
    env: Mapping[str, str] | None = None,
) -> None:
    """Атомарно сохраняет API-ключи, не трогая остальные строки .env."""

    normalized_id, normalized_hash = validate_api_credentials(api_id, api_hash)
    values = os.environ if env is None else env
    _reject_environment_override(values, normalized_id, normalized_hash)

    path = Path(env_path)
    lines = _read_lines(path)

    keep: list[str] = []
    for line in lines:
        key = _line_key(line)
        if key in API_ID_KEYS or key in API_HASH_KEYS:
            continue
        keep.append(line)

    while keep and not keep[-1].strip():
        keep.pop()
    keep.append(f"TELEGRAM_API_ID={normalized_id}")
    keep.append(f"TELEGRAM_API_HASH={normalized_hash}")

    _atomic_write(path, "\n".join(keep) + "\n")


def save_session_string(env_path: Path, session_string: str) -> None:
    """Сохраняет обновлённую строковую сессию Telethon в .env."""

    path = Path(env_path)
    lines = _read_lines(path)
    keep = [line for line in lines if _line_key(line) not in SESSION_KEYS]
    while keep and not keep[-1].strip():
        keep.pop()

    session = session_string.strip()
    if session:
        keep.append(f"TG_SESSION={session}")

    _atomic_write(path, "\n".join(keep) + ("\n" if keep else ""))


def session_path(values: Mapping[str, str]) -> Path:
    """Каталог сессии: LOCALAPPDATA на Windows, XDG на остальных системах."""

    local_app_data = values.get("LOCALAPPDATA")
    if local_app_data:
        base = Path(local_app_data)
    else:
        xdg_data_home = values.get("XDG_DATA_HOME")
        base = Path(xdg_data_home) if xdg_data_home else Path.home() / ".local" / "share"
    return base / SESSION_DIR_NAME / "session"


def _merged_values(
    env_path: Path,
    env: Mapping[str, str] | None,
) -> dict[str, str]:
    file_values: dict[str, str] = {}
    if env_path.exists():
        try:
            file_values = {
                key: value
                for key, value in dotenv_values(env_path, encoding="utf-8").items()
                if value is not None
            }
        except (OSError, UnicodeDecodeError) as exc:
            raise CredentialError("Не удалось прочитать файл .env.") from exc

    environment = os.environ if env is None else env
    return {**file_values, **environment}


def _first(values: Mapping[str, str], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = values.get(key)
        if value and value.strip():
            return value.strip()
    return None


def _reject_environment_override(
    values: Mapping[str, str],
    api_id: int,
    api_hash: str,
) -> None:
    for key in API_ID_KEYS:
        value = values.get(key)
        if value and value.strip() and value.strip() != str(api_id):
            raise ValueError(
                f"{key} задан в окружении и перекрывает .env. "
                "Исправь или удали переменную окружения."
            )
    for key in API_HASH_KEYS:
        value = values.get(key)
        if value and value.strip() and value.strip() != api_hash:
            raise ValueError(
                f"{key} задан в окружении и перекрывает .env. "
                "Исправь или удали переменную окружения."
            )


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CredentialError("Файл .env повреждён и не является текстом UTF-8.") from exc
    except OSError as exc:
        raise CredentialError("Не удалось прочитать файл .env.") from exc


def _line_key(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return ""
    return stripped.split("=", 1)[0].strip()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".env.",
        dir=str(path.parent),
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, path)
    except OSError as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise ValueError(
            "Не удалось сохранить настройки. Проверь права на папку проекта."
        ) from exc
