"""Tkinter-интерфейс клиента."""

from .login import LoginView
from .main_window import MainWindow, outcome_tone
from .setup import SetupView
from .theme import PALETTE, Theme

__all__ = [
    "LoginView",
    "MainWindow",
    "PALETTE",
    "SetupView",
    "Theme",
    "outcome_tone",
]
