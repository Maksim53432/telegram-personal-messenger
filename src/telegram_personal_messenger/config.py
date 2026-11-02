"""Загрузка конфигурации из .env."""
import os
from pathlib import Path

from dotenv import load_dotenv


def load_config(env_path: Path | None = None) -> tuple[int, str, str]:
    """
    Возвращает (api_id, api_hash, session_str).
    session_str может быть пустой — тогда потребуется вход.
    """
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    load_dotenv(env_path)

    api_id_raw = os.getenv("TG_API_ID")
    api_hash = os.getenv("TG_API_HASH")
    session = os.getenv("TG_SESSION", "").strip()

    if not api_id_raw or not api_hash:
        raise SystemExit(
            "В .env должны быть TG_API_ID и TG_API_HASH.\n"
            "Возьми их на https://my.telegram.org/apps"
        )

    try:
        api_id = int(api_id_raw)
    except ValueError:
        raise SystemExit(f"TG_API_ID = {api_id_raw!r} — это не число.")

    return api_id, api_hash, session