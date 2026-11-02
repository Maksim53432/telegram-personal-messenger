"""Первый запуск: ввод API ID и API Hash."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from pathlib import Path
from typing import Callable

from ..config import (
    CredentialError,
    Settings,
    load_settings,
    read_api_credentials,
    save_api_credentials,
    validate_api_credentials,
)
from .theme import Theme
from .widgets import FlatButton


class SetupView(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        env_path: Path,
        on_saved: Callable[[Settings], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        self.env_path = env_path
        self._on_saved = on_saved
        self._on_cancel = on_cancel
        self._alive = True
        self._saving = False

        super().__init__(parent, bg=self.palette.window)
        self._build()
        self._prefill()

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        card = tk.Frame(
            self,
            bg=self.palette.surface,
            padx=36,
            pady=30,
            highlightthickness=1,
            highlightbackground=self.palette.line_soft,
        )
        card.grid(row=0, column=0)

        logo = tk.Canvas(
            card,
            width=64,
            height=64,
            bg=self.palette.surface,
            highlightthickness=0,
            bd=0,
        )
        logo.pack()
        logo.create_oval(2, 2, 62, 62, fill=self.palette.active, outline="")
        logo.create_text(
            32,
            32,
            text="TG",
            fill=self.palette.white,
            font=self.theme.font(18, "bold"),
        )

        tk.Label(
            card,
            text="Первый запуск",
            bg=self.palette.surface,
            fg=self.palette.text,
            font=self.theme.font(19, "bold"),
        ).pack(pady=(12, 2))
        tk.Label(
            card,
            text="Введи ключи приложения Telegram. Вход в аккаунт будет следующим шагом.",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(9),
            justify="center",
            wraplength=390,
        ).pack(pady=(0, 14))

        link = tk.Label(
            card,
            text="Получить API ID и API Hash на my.telegram.org/apps",
            bg=self.palette.surface,
            fg=self.palette.accent,
            font=self.theme.font(9),
            cursor="hand2",
        )
        link.pack(pady=(0, 16))
        link.bind(
            "<Button-1>",
            lambda _event: webbrowser.open("https://my.telegram.org/apps"),
        )

        self.api_id_entry = self._labeled_entry(card, "API ID")
        self.api_id_entry.bind("<KeyRelease>", self._refresh_save_button)

        self.api_hash_entry = self._labeled_entry(card, "API Hash", show="•")
        self.api_hash_entry.bind("<KeyRelease>", self._refresh_save_button)

        self.show_hash = tk.BooleanVar(value=False)
        show = tk.Checkbutton(
            card,
            text="Показать API Hash",
            variable=self.show_hash,
            command=self._toggle_hash,
            bg=self.palette.surface,
            fg=self.palette.muted,
            activebackground=self.palette.surface,
            activeforeground=self.palette.text,
            selectcolor=self.palette.sidebar_alt,
            font=self.theme.font(9),
            bd=0,
            highlightthickness=0,
        )
        show.pack(anchor="w", pady=(2, 12))

        self.save_button = FlatButton(
            card,
            self.theme,
            "Сохранить и продолжить",
            self._save,
            bg=self.palette.accent,
            fg=self.palette.window,
            hover_bg=self.palette.accent_dark,
            hover_fg=self.palette.window,
            font=self.theme.font(10, "bold"),
            padx=18,
            pady=9,
        )
        self.save_button.pack(fill="x")
        self.save_button.set_enabled(False)

        self.cancel_button = FlatButton(
            card,
            self.theme,
            "Отмена",
            self._cancel,
            bg=self.palette.surface,
            fg=self.palette.muted,
            hover_bg=self.palette.hover,
            hover_fg=self.palette.text,
            font=self.theme.font(9),
            padx=10,
            pady=6,
        )
        self.cancel_button.pack(pady=(8, 0))

        self.status_label = tk.Label(
            card,
            text="",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(9),
            justify="left",
            wraplength=390,
        )
        self.status_label.pack(fill="x", pady=(12, 0))

    def _labeled_entry(
        self,
        parent: tk.Misc,
        label: str,
        show: str | None = None,
    ) -> tk.Entry:
        tk.Label(
            parent,
            text=label,
            bg=self.palette.surface,
            fg=self.palette.text_soft,
            font=self.theme.font(9),
        ).pack(anchor="w", pady=(0, 5))
        entry = tk.Entry(
            parent,
            bg=self.palette.sidebar_alt,
            fg=self.palette.text,
            insertbackground=self.palette.accent,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=self.palette.line_soft,
            highlightcolor=self.palette.accent,
            font=self.theme.font(11),
            show=show,
        )
        entry.pack(fill="x", ipady=7, ipadx=8, pady=(0, 10))
        return entry

    def _prefill(self) -> None:
        try:
            api_id, api_hash = read_api_credentials(self.env_path)
        except CredentialError:
            api_id, api_hash = "", ""
        if api_id:
            self.api_id_entry.insert(0, api_id)
        if api_hash:
            self.api_hash_entry.insert(0, api_hash)
        self._refresh_save_button()

    def _toggle_hash(self) -> None:
        self.api_hash_entry.configure(show="" if self.show_hash.get() else "•")

    def _refresh_save_button(self, _event: tk.Event | None = None) -> None:
        enabled = False
        try:
            validate_api_credentials(
                self.api_id_entry.get(),
                self.api_hash_entry.get(),
            )
        except CredentialError:
            enabled = False
        else:
            enabled = True
        self.save_button.set_enabled(enabled and not self._saving)

    def _save(self) -> None:
        if self._saving:
            return
        api_id = self.api_id_entry.get().strip()
        api_hash = self.api_hash_entry.get().strip()
        try:
            validate_api_credentials(api_id, api_hash)
        except CredentialError as exc:
            self._status(self._credential_message(exc), "error")
            return

        self._saving = True
        self._set_fields_enabled(False)
        self._status("Сохраняю настройки…", "muted")
        self.update_idletasks()
        try:
            save_api_credentials(self.env_path, api_id, api_hash)
            settings = load_settings(self.env_path)
        except (CredentialError, ValueError) as exc:
            self._saving = False
            self._set_fields_enabled(True)
            self._status(self._credential_message(exc), "error")
            return
        except OSError:
            self._saving = False
            self._set_fields_enabled(True)
            self._status("Не удалось сохранить .env. Проверь права на папку.", "error")
            return

        self._alive = False
        self._on_saved(settings)

    def _set_fields_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.api_id_entry.configure(state=state)
        self.api_hash_entry.configure(state=state)
        self.save_button.set_enabled(enabled)
        self.cancel_button.set_enabled(enabled)
        if enabled:
            self._refresh_save_button()

    def _cancel(self) -> None:
        if self._saving:
            return
        self._alive = False
        self._on_cancel()

    def _status(self, text: str, tone: str) -> None:
        colors = {
            "error": self.palette.red,
            "success": self.palette.green,
            "muted": self.palette.muted,
        }
        self.status_label.configure(text=text, fg=colors.get(tone, self.palette.muted))

    def _credential_message(self, error: Exception) -> str:
        text = str(error)
        if "окружении" in text or "перекрывает" in text:
            if "HASH" in text:
                return "Переменная окружения с API Hash перекрывает .env. Исправь или удали её."
            return "Переменная окружения с API ID перекрывает .env. Исправь или удали её."
        if "must be an integer" in text:
            return "API ID должен быть положительным целым числом."
        if "32 hexadecimal" in text:
            return "API Hash должен содержать 32 шестнадцатеричных символа."
        if "TELEGRAM_API_ID" in text or "TG_API_ID" in text:
            return "Введи API ID и API Hash."
        return "Не удалось сохранить настройки. Проверь данные и права на папку проекта."

    def destroy(self) -> None:
        self._alive = False
        super().destroy()
