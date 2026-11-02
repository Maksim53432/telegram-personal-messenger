"""Экран входа в Telegram: телефон, код и пароль 2FA."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from ..errors import TelegramServiceError
from ..telegram_service import TelegramService
from .text import error_text
from .theme import Theme
from .widgets import FlatButton

Submit = Callable[[Any, Callable[[Any], None], Callable[[Exception], None]], None]


class LoginView(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        service: TelegramService,
        submit: Submit,
        on_success: Callable[[], None],
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        self.service = service
        self._submit_operation = submit
        self._on_success = on_success
        self._alive = True
        self._busy = False
        self._step = "phone"
        self._phone = ""

        super().__init__(parent, bg=self.palette.window)
        self._build()
        self._show_step("phone")

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
            width=72,
            height=72,
            bg=self.palette.surface,
            highlightthickness=0,
            bd=0,
        )
        logo.pack()
        logo.create_oval(
            2,
            2,
            70,
            70,
            fill=self.palette.active,
            outline="",
        )
        logo.create_text(
            36,
            36,
            text="✈",
            fill=self.palette.white,
            font=self.theme.font(26, "bold"),
        )

        tk.Label(
            card,
            text="Telegram",
            bg=self.palette.surface,
            fg=self.palette.text,
            font=self.theme.font(20, "bold"),
        ).pack(pady=(12, 2))
        tk.Label(
            card,
            text="Вход в личный аккаунт",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(10),
        ).pack(pady=(0, 18))

        self.phone_frame = self._build_phone_step(card)
        self.code_frame = self._build_code_step(card)
        self.password_frame = self._build_password_step(card)

        self.status_label = tk.Label(
            card,
            text="",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(9),
            justify="left",
            wraplength=360,
        )
        self.status_label.pack(fill="x", pady=(14, 0))

        tk.Label(
            card,
            text="Код и пароль двухэтапной проверки не сохраняются на диске.",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(8),
            justify="center",
            wraplength=360,
        ).pack(pady=(10, 0))

        self._entries = [
            self.phone_entry,
            self.code_entry,
            self.password_entry,
        ]
        self._buttons = [
            self.phone_button,
            self.code_button,
            self.password_button,
            self.change_phone_button,
        ]

    def _build_phone_step(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.palette.surface)
        self._field_label(frame, "Номер телефона")
        self.phone_entry = self._entry(frame)
        self.phone_entry.bind("<Return>", lambda _event: self._request_code())
        self.phone_button = FlatButton(
            frame,
            self.theme,
            "Получить код",
            self._request_code,
            bg=self.palette.accent,
            fg=self.palette.window,
            hover_bg=self.palette.accent_dark,
            hover_fg=self.palette.window,
            font=self.theme.font(10, "bold"),
            padx=18,
            pady=9,
        )
        self.phone_button.pack(fill="x", pady=(16, 0))
        tk.Label(
            frame,
            text="Например: +7 999 123-45-67",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(8),
        ).pack(anchor="w", pady=(8, 0))
        return frame

    def _build_code_step(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.palette.surface)
        self.phone_hint = tk.Label(
            frame,
            text="",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(9),
        )
        self.phone_hint.pack(anchor="w", pady=(0, 10))
        self._field_label(frame, "Код из Telegram")
        self.code_entry = self._entry(frame)
        self.code_entry.bind("<Return>", lambda _event: self._sign_in_code())
        self.code_button = FlatButton(
            frame,
            self.theme,
            "Войти",
            self._sign_in_code,
            bg=self.palette.accent,
            fg=self.palette.window,
            hover_bg=self.palette.accent_dark,
            hover_fg=self.palette.window,
            font=self.theme.font(10, "bold"),
            padx=18,
            pady=9,
        )
        self.code_button.pack(fill="x", pady=(16, 0))
        self.change_phone_button = FlatButton(
            frame,
            self.theme,
            "Изменить номер",
            lambda: self._show_step("phone"),
            bg=self.palette.surface,
            fg=self.palette.accent,
            hover_bg=self.palette.hover,
            hover_fg=self.palette.accent,
            font=self.theme.font(9),
            padx=4,
            pady=4,
        )
        self.change_phone_button.pack(pady=(8, 0))
        return frame

    def _build_password_step(self, parent: tk.Misc) -> tk.Frame:
        frame = tk.Frame(parent, bg=self.palette.surface)
        tk.Label(
            frame,
            text="Аккаунт защищён паролем. Введи пароль двухэтапной проверки.",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(9),
            justify="left",
            wraplength=360,
        ).pack(anchor="w", pady=(0, 10))
        self._field_label(frame, "Пароль")
        self.password_entry = self._entry(frame, show="•")
        self.password_entry.bind("<Return>", lambda _event: self._sign_in_password())
        self.password_button = FlatButton(
            frame,
            self.theme,
            "Войти",
            self._sign_in_password,
            bg=self.palette.accent,
            fg=self.palette.window,
            hover_bg=self.palette.accent_dark,
            hover_fg=self.palette.window,
            font=self.theme.font(10, "bold"),
            padx=18,
            pady=9,
        )
        self.password_button.pack(fill="x", pady=(16, 0))
        return frame

    def _field_label(self, parent: tk.Misc, text: str) -> None:
        tk.Label(
            parent,
            text=text,
            bg=self.palette.surface,
            fg=self.palette.text_soft,
            font=self.theme.font(9),
        ).pack(anchor="w", pady=(0, 5))

    def _entry(self, parent: tk.Misc, show: str | None = None) -> tk.Entry:
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
        entry.pack(fill="x", ipady=7, ipadx=8)
        return entry

    def _show_step(self, step: str) -> None:
        self._step = step
        for frame in (self.phone_frame, self.code_frame, self.password_frame):
            frame.pack_forget()
        if step == "phone":
            self.phone_frame.pack(fill="x")
            self.phone_entry.focus_set()
        elif step == "code":
            self.code_frame.pack(fill="x")
            self.phone_hint.configure(text=f"Код отправлен на {self._phone}")
            self.code_entry.focus_set()
        else:
            self.password_frame.pack(fill="x")
            self.password_entry.focus_set()

    def _request_code(self) -> None:
        if self._busy:
            return
        phone = self.phone_entry.get().strip()
        if not phone:
            self._status(error_text(TelegramServiceError("login_phone_invalid")), "error")
            self.phone_entry.focus_set()
            return
        self._phone = phone
        self._set_busy(True)
        self._status("Отправляю код в Telegram…", "muted")
        self._submit(
            self.service.request_login_code(phone),
            self._on_code_sent,
            self._on_error,
        )

    def _on_code_sent(self, _result: Any) -> None:
        self._set_busy(False)
        self._status("Код отправлен. Проверь сообщения в Telegram.", "success")
        self._show_step("code")

    def _sign_in_code(self) -> None:
        if self._busy:
            return
        code = self.code_entry.get().strip()
        if not code:
            self._status("Введи код из Telegram.", "error")
            self.code_entry.focus_set()
            return
        self._set_busy(True)
        self._status("Проверяю код…", "muted")
        self._submit(
            self.service.sign_in_code(self._phone, code),
            self._on_code_signed,
            self._on_error,
        )

    def _on_code_signed(self, result: Any) -> None:
        self._set_busy(False)
        if result is True:
            self._finish()
            return
        self._status("Нужен пароль двухэтапной проверки.", "muted")
        self._show_step("password")

    def _sign_in_password(self) -> None:
        if self._busy:
            return
        password = self.password_entry.get()
        if not password:
            self._status("Введи пароль двухэтапной проверки.", "error")
            self.password_entry.focus_set()
            return
        self._set_busy(True)
        self._status("Проверяю пароль…", "muted")
        self._submit(
            self.service.sign_in_password(password),
            lambda _result: self._finish(),
            self._on_error,
        )

    def _finish(self) -> None:
        if not self._alive:
            return
        self._alive = False
        self._set_busy(False)
        for entry in (self.phone_entry, self.code_entry, self.password_entry):
            entry.delete(0, "end")
        self._on_success()

    def _on_error(self, error: Exception) -> None:
        if not self._alive:
            return
        self._set_busy(False)
        self._status(error_text(error), "error")
        if self._step == "code":
            self.code_entry.delete(0, "end")
            self.code_entry.focus_set()
        elif self._step == "password":
            self.password_entry.delete(0, "end")
            self.password_entry.focus_set()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for entry in self._entries:
            entry.configure(state=state)
        for button in self._buttons:
            button.set_enabled(not busy)

    def _status(self, text: str, tone: str) -> None:
        colors = {
            "error": self.palette.red,
            "success": self.palette.green,
            "muted": self.palette.muted,
        }
        self.status_label.configure(text=text, fg=colors.get(tone, self.palette.muted))

    def _submit(self, coro, on_success, on_error) -> None:
        try:
            self._submit_operation(coro, on_success, on_error)
        except Exception as exc:
            self._on_error(exc)

    def destroy(self) -> None:
        self._alive = False
        super().destroy()
