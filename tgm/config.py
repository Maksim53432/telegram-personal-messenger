"""Settings from `.env` and the process environment.

Recognised keys (environment wins over the file):

    TG_API_ID, TG_API_HASH   application keys from https://my.telegram.org/apps
    TG_SESSION               optional Telethon StringSession, imported once
    TG_PROXY                 optional socks5://, socks4://, http:// or t.me/proxy link
    TG_DATA_DIR              where the session and caches live (default: ./data)
    TG_NOTIFY                0 disables desktop notifications
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

PROJECT_DIR = Path(__file__).resolve().parent.parent


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Proxy:
    kind: str  # socks5 | socks4 | http | mtproto
    host: str
    port: int
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    secret: str | None = field(default=None, repr=False)

    def telethon_kwargs(self) -> dict:
        """Keyword arguments for TelegramClient (proxy and, for MTProto, connection)."""
        if self.kind == "mtproto":
            from telethon import connection

            secret = self.secret or ""
            # "dd" secrets ask for random padding, "ee" for fake-TLS which Telethon lacks.
            if secret.startswith("ee"):
                raise ConfigError("Fake-TLS MTProto secrets (ee...) are not supported by Telethon.")
            conn = (
                connection.ConnectionTcpMTProxyRandomizedIntermediate
                if secret.startswith("dd")
                else connection.ConnectionTcpMTProxyIntermediate
            )
            return {"connection": conn, "proxy": (self.host, self.port, secret)}
        return {
            "proxy": {
                "proxy_type": self.kind,
                "addr": self.host,
                "port": self.port,
                "username": self.username,
                "password": self.password,
                "rdns": True,
            }
        }


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str = field(repr=False)
    data_dir: Path
    session_string: str = field(default="", repr=False)
    proxy: Proxy | None = None
    notify: bool = True

    @property
    def session_file(self) -> Path:
        return self.data_dir / "account.session"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


def read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE parser: comments, blank lines, optional quotes, `export`."""
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def parse_proxy(value: str) -> Proxy | None:
    text = value.strip()
    if not text:
        return None
    if "://" not in text:
        text = "socks5://" + text
    url = urlsplit(text)
    scheme = url.scheme.lower()

    if scheme in ("tg", "mtproxy") or (
        url.hostname in ("t.me", "telegram.me") and url.path.rstrip("/").endswith("proxy")
    ):
        query = parse_qs(url.query)
        server = query.get("server", [""])[0]
        port = query.get("port", [""])[0]
        secret = query.get("secret", [""])[0]
        if not server or not port.isdecimal() or not secret:
            raise ConfigError("MTProto proxy link needs server, port and secret.")
        return Proxy("mtproto", server, _port(int(port)), secret=secret)

    if scheme == "socks5h":
        scheme = "socks5"
    if scheme not in ("socks5", "socks4", "http"):
        raise ConfigError(f"Unsupported proxy scheme: {scheme}")
    try:
        port = url.port
    except ValueError:
        port = None
    if not url.hostname or not port:
        raise ConfigError("Proxy must look like socks5://host:port")
    return Proxy(
        scheme,
        url.hostname,
        _port(port),
        username=unquote(url.username) if url.username else None,
        password=unquote(url.password) if url.password else None,
    )


def _port(port: int) -> int:
    if not 1 <= port <= 65535:
        raise ConfigError("Proxy port out of range.")
    return port


def load_settings(env_file: Path | None = None, environ: dict[str, str] | None = None) -> Settings:
    values = read_env_file(env_file or PROJECT_DIR / ".env")
    values.update({k: v for k, v in (os.environ if environ is None else environ).items() if k.startswith("TG_")})

    api_id = values.get("TG_API_ID", "").strip()
    api_hash = values.get("TG_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise ConfigError("TG_API_ID and TG_API_HASH must be set (see .env.example).")
    if not api_id.isdecimal():
        raise ConfigError("TG_API_ID must be a number.")
    if len(api_hash) != 32 or any(c not in "0123456789abcdefABCDEF" for c in api_hash):
        raise ConfigError("TG_API_HASH must be 32 hex characters.")

    data_dir = Path(values.get("TG_DATA_DIR") or PROJECT_DIR / "data").expanduser()
    return Settings(
        api_id=int(api_id),
        api_hash=api_hash.lower(),
        data_dir=data_dir,
        session_string=values.get("TG_SESSION", "").strip(),
        proxy=parse_proxy(values.get("TG_PROXY", "")),
        notify=values.get("TG_NOTIFY", "1").strip() not in ("0", "false", "no", "off"),
    )
