from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Recipient:
    id: int
    display_name: str
    username: str | None


@dataclass(frozen=True)
class SendOutcome:
    kind: Literal["sent", "failed", "unknown"]
    message: str


def validate_message(text: str) -> str:
    if not text.strip():
        raise ValueError("Enter a message before sending.")
    return text
