from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile
from typing import Mapping

from dotenv import dotenv_values


CREDENTIAL_KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH")
_CREDENTIAL_ASSIGNMENT = re.compile(r"^\s*(?:export\s+)?(TELEGRAM_API_ID|TELEGRAM_API_HASH)\s*=")


class CredentialError(ValueError):
    """Telegram API credentials are missing or invalid."""


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str
    session_path: Path


def validate_api_credentials(api_id_value: str | None, api_hash_value: str | None) -> tuple[int, str]:
    raw_id = (api_id_value or "").strip()
    if not raw_id:
        raise CredentialError("Set TELEGRAM_API_ID in the local .env file.")
    if not raw_id.isascii() or not raw_id.isdecimal():
        raise CredentialError("TELEGRAM_API_ID must be an integer greater than zero.")
    try:
        api_id = int(raw_id)
    except ValueError:
        raise CredentialError("TELEGRAM_API_ID must be an integer greater than zero.") from None
    if api_id <= 0:
        raise CredentialError("TELEGRAM_API_ID must be an integer greater than zero.")

    api_hash = (api_hash_value or "").strip()
    if not api_hash:
        raise CredentialError("Set TELEGRAM_API_HASH in the local .env file.")
    if len(api_hash) != 32 or any(char not in "0123456789abcdefABCDEF" for char in api_hash):
        raise CredentialError("TELEGRAM_API_HASH must contain 32 hexadecimal characters.")

    return api_id, api_hash


def read_api_credentials(
    env_path: Path,
    env: Mapping[str, str] | None = None,
) -> tuple[str, str]:
    values = dict(dotenv_values(env_path))
    values.update(dict(os.environ if env is None else env))
    return (
        str(values.get("TELEGRAM_API_ID") or ""),
        str(values.get("TELEGRAM_API_HASH") or ""),
    )


def load_settings(
    env_path: Path,
    env: Mapping[str, str] | None = None,
) -> Settings:
    values = dict(dotenv_values(env_path))
    values.update(dict(os.environ if env is None else env))

    api_id, api_hash = validate_api_credentials(
        values.get("TELEGRAM_API_ID"),
        values.get("TELEGRAM_API_HASH"),
    )

    local_app_data = values.get("LOCALAPPDATA") or os.getenv("LOCALAPPDATA")
    if not local_app_data:
        raise ValueError("Windows LOCALAPPDATA is unavailable.")

    session_path = Path(local_app_data) / "TelegramPersonalMessenger" / "account"
    session_path.parent.mkdir(parents=True, exist_ok=True)
    return Settings(api_id=api_id, api_hash=api_hash, session_path=session_path)


def _credential_file_content(env_path: Path, api_id: str, api_hash: str) -> str:
    try:
        content = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    except (OSError, UnicodeError):
        raise CredentialError("Could not read the local .env file.") from None

    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines(keepends=True)
    values = {
        "TELEGRAM_API_ID": api_id,
        "TELEGRAM_API_HASH": api_hash,
    }
    written: set[str] = set()
    updated: list[str] = []

    for line in lines:
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        match = _CREDENTIAL_ASSIGNMENT.match(body)
        if match is None:
            updated.append(line)
            continue

        key = match.group(1)
        if key in written:
            continue
        updated.append(f"{key}={values[key]}{ending}")
        written.add(key)

    for key in CREDENTIAL_KEYS:
        if key in written:
            continue
        if updated and not updated[-1].endswith(("\n", "\r")):
            updated[-1] += newline
        updated.append(f"{key}={values[key]}{newline}")

    return "".join(updated)


def save_api_credentials(
    env_path: Path,
    api_id_value: str,
    api_hash_value: str,
    env: Mapping[str, str] | None = None,
) -> None:
    api_id, api_hash = validate_api_credentials(api_id_value, api_hash_value)
    normalized_id = str(api_id)
    environment = os.environ if env is None else env

    if "TELEGRAM_API_ID" in environment:
        override = str(environment["TELEGRAM_API_ID"])
        try:
            effective_id, _ = validate_api_credentials(override, api_hash)
        except CredentialError:
            raise CredentialError(
                "TELEGRAM_API_ID is set in the environment and overrides the local value."
            ) from None
        if effective_id != api_id:
            raise CredentialError(
                "TELEGRAM_API_ID is set in the environment and overrides the local value."
            )

    if "TELEGRAM_API_HASH" in environment:
        override = str(environment["TELEGRAM_API_HASH"])
        try:
            _, effective_hash = validate_api_credentials(normalized_id, override)
        except CredentialError:
            raise CredentialError(
                "TELEGRAM_API_HASH is set in the environment and overrides the local value."
            ) from None
        if effective_hash != api_hash:
            raise CredentialError(
                "TELEGRAM_API_HASH is set in the environment and overrides the local value."
            )

    content = _credential_file_content(env_path, normalized_id, api_hash)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f"{env_path.name}.",
            suffix=".tmp",
            dir=env_path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary_file:
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, env_path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise CredentialError("Could not save Telegram API credentials.") from None
