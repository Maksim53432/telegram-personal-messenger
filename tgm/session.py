"""Persistent Telethon session.

A StringSession only holds the auth key, so every start would begin with an
empty entity cache and no update state. On first run the string from
TG_SESSION is copied into an SQLite session file, which keeps both.
"""

from __future__ import annotations

import os
from pathlib import Path

from telethon.sessions import SQLiteSession, StringSession


def open_session(session_file: Path, session_string: str = "") -> SQLiteSession:
    session_file.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(session_file.parent, 0o700)
    fresh = not session_file.exists()
    # SQLiteSession appends ".session" itself.
    session = SQLiteSession(str(session_file.with_suffix("")))
    if fresh and session_string:
        imported = StringSession(session_string)
        session.set_dc(imported.dc_id, imported.server_address, imported.port)
        session.auth_key = imported.auth_key
        session.save()
    if session_file.exists():
        os.chmod(session_file, 0o600)
    return session
