"""Тёмная тема и общие настройки оформления."""

from __future__ import annotations

from dataclasses import dataclass
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    window: str = "#0E1621"
    sidebar: str = "#17212B"
    sidebar_alt: str = "#1C2733"
    panel: str = "#17212B"
    surface: str = "#1E2A36"
    surface_alt: str = "#232F3B"
    hover: str = "#202B36"
    active: str = "#2B5278"
    active_hover: str = "#32608C"
    accent: str = "#64B5EF"
    accent_dark: str = "#4A9BD6"
    text: str = "#F2F5F7"
    text_soft: str = "#C7D2DB"
    muted: str = "#7D8E9E"
    line: str = "#101921"
    line_soft: str = "#263442"
    out_bubble: str = "#2B5278"
    in_bubble: str = "#182533"
    green: str = "#4FCE5D"
    red: str = "#E05D5D"
    yellow: str = "#E8B44F"
    white: str = "#FFFFFF"


PALETTE = Palette()

_FAMILY_CANDIDATES = (
    "Segoe UI",
    "SF Pro Display",
    "Inter",
    "Noto Sans",
    "DejaVu Sans",
    "Liberation Sans",
    "Arial",
)

_MONO_CANDIDATES = (
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "Courier New",
)


class Theme:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self.palette = PALETTE
        self.family = _pick_family(root, _FAMILY_CANDIDATES, "TkDefaultFont")
        self.mono_family = _pick_family(root, _MONO_CANDIDATES, "TkFixedFont")
        self._configure_root()
        self._configure_ttk()

    def font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.family, size, weight)

    def mono(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return (self.mono_family, size, weight)

    def _configure_root(self) -> None:
        try:
            self.root.configure(bg=self.palette.window)
        except tk.TclError:
            pass
        try:
            self.root.option_add("*Font", self.font(10))
            self.root.option_add("*selectBackground", self.palette.active)
            self.root.option_add("*selectForeground", self.palette.white)
            self.root.option_add("*Entry.insertBackground", self.palette.accent)
        except tk.TclError:
            pass

    def _configure_ttk(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            try:
                style.theme_use("clam")
            except tk.TclError:
                pass

        p = self.palette
        style.configure(
            "Vertical.TScrollbar",
            background=p.surface_alt,
            troughcolor=p.window,
            bordercolor=p.window,
            arrowcolor=p.muted,
            darkcolor=p.surface_alt,
            lightcolor=p.surface_alt,
            width=8,
            arrowsize=8,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", p.hover), ("pressed", p.active)],
        )
        style.configure(
            "TEntry",
            fieldbackground=p.surface,
            foreground=p.text,
            insertcolor=p.accent,
            bordercolor=p.line_soft,
            lightcolor=p.line_soft,
            darkcolor=p.line_soft,
            padding=(10, 8),
        )
        style.configure(
            "TCombobox",
            fieldbackground=p.surface,
            foreground=p.text,
            background=p.surface,
            arrowcolor=p.muted,
            bordercolor=p.line_soft,
            padding=(8, 6),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", p.surface)],
            foreground=[("readonly", p.text)],
        )
        style.configure(
            "Accent.TButton",
            font=self.font(10, "bold"),
            padding=(16, 9),
            background=p.accent,
            foreground=p.window,
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", p.line_soft), ("active", p.accent_dark)],
            foreground=[("disabled", p.muted), ("!disabled", p.window)],
        )
        style.configure(
            "Ghost.TButton",
            font=self.font(10),
            padding=(12, 8),
            background=p.surface,
            foreground=p.text,
            borderwidth=0,
        )
        style.map(
            "Ghost.TButton",
            background=[("active", p.hover), ("disabled", p.surface)],
            foreground=[("disabled", p.muted), ("!disabled", p.text)],
        )
        style.configure(
            "TCheckbutton",
            background=p.surface,
            foreground=p.text_soft,
            font=self.font(9),
        )
        style.map(
            "TCheckbutton",
            background=[("active", p.surface)],
            foreground=[("active", p.text)],
        )


def _pick_family(root: tk.Misc, candidates: tuple[str, ...], fallback: str) -> str:
    try:
        available = set(tkfont.families(root))
    except tk.TclError:
        return fallback
    for family in candidates:
        if family in available:
            return family
    return fallback
