from collections.abc import Callable
import tkinter as tk
from tkinter import ttk
from typing import Any

from .async_worker import AsyncWorker
from .config import (
    CredentialError,
    Settings,
    load_settings,
    read_api_credentials,
    save_api_credentials,
    validate_api_credentials,
)
from .controller import MessengerController
from .models import Recipient
from .telegram_service import TelegramService, TelegramServiceError


COLORS = {
    "background": "#EEF3F7",
    "surface": "#FFFFFF",
    "ink": "#17324D",
    "muted": "#5C7185",
    "accent": "#168AC4",
    "accent_dark": "#0E6FA4",
    "line": "#D7E1E8",
    "error": "#A83232",
    "success": "#176B4D",
    "warning": "#8A5A12",
}


def recipient_label(recipient: Recipient) -> str:
    if recipient.username:
        return f"{recipient.display_name} (@{recipient.username})"
    return recipient.display_name


def status_message(state: str, message: str) -> str:
    if state == "sending":
        return "Отправляю…"
    if state == "sent":
        return "Сообщение отправлено."
    if state == "unknown":
        return "Результат неясен: сообщение могло уйти. Приложение не повторяло отправку."

    translations = {
        "Enter a message before sending.": "Сначала введи текст сообщения.",
        "Choose a recipient before sending.": "Сначала выбери получателя.",
        "Select a person from the chat list or username search.": "Заново выбери человека из списка или найди его по @username.",
        "Telegram rejected the message. Check the recipient and try again.": "Telegram не принял сообщение. Проверь получателя и ограничения чата.",
        "Could not connect to Telegram. Check your connection.": "Не удалось подключиться к Telegram. Проверь интернет.",
        "Could not send the message. Check the connection and try again.": "Не удалось отправить сообщение. Проверь интернет; приложение не повторяло отправку.",
        "Could not send the message.": "Не удалось отправить сообщение.",
        "Could not start the send operation.": "Не удалось запустить отправку.",
    }
    return translations.get(message, "Не удалось отправить сообщение. Проверь получателя и интернет.")


class MessengerWindow:
    def __init__(
        self,
        root: tk.Tk,
        service: TelegramService,
        worker: AsyncWorker,
        auto_open_login: bool = False,
    ) -> None:
        self.root = root
        self.service = service
        self.worker = worker
        self._auto_open_login = auto_open_login
        self.controller = MessengerController(service, worker, self._on_send_state)
        self._recipient_by_label: dict[str, Recipient] = {}
        self._selected_recipient: Recipient | None = None
        self._login_window: LoginWindow | None = None
        self._closing = False
        self._destroyed = False

        self._configure_window()
        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(50, self._poll_worker)
        self._set_status("Проверяю подключение к Telegram…", "muted")
        self._submit(
            self.service.is_authorized(),
            self._on_authorization_checked,
            lambda error: self._show_operation_error(error, "connect"),
        )

    def _configure_window(self) -> None:
        self.root.title("Личное сообщение · Telegram")
        self.root.geometry("620x740")
        self.root.minsize(520, 650)
        self.root.configure(bg=COLORS["background"])

        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Messenger.TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            padding=(9, 8),
            bordercolor=COLORS["line"],
        )
        style.configure(
            "Messenger.TCombobox",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            padding=(8, 7),
        )
        style.configure(
            "Messenger.TButton",
            font=("Segoe UI", 10),
            padding=(12, 8),
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 11),
            padding=(14, 10),
            background=COLORS["accent"],
            foreground=COLORS["surface"],
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", "#A9C8D9"), ("active", COLORS["accent_dark"])],
            foreground=[("disabled", "#F7FAFC"), ("!disabled", COLORS["surface"])],
        )

    def _build_widgets(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self.root, bg=COLORS["ink"], padx=28, pady=22)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(
            header,
            text="ЛИЧНЫЙ АККАУНТ · TELEGRAM",
            bg=COLORS["ink"],
            fg="#79C7E8",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Новое сообщение",
            bg=COLORS["ink"],
            fg=COLORS["surface"],
            font=("Segoe UI Semibold", 20),
        ).pack(anchor="w", pady=(5, 0))
        tk.Label(
            header,
            text="Один клик по кнопке — одна попытка отправки.",
            bg=COLORS["ink"],
            fg="#C3D3DF",
            font=("Segoe UI", 10),
        ).pack(anchor="w", pady=(3, 0))

        content = tk.Frame(self.root, bg=COLORS["background"], padx=22, pady=18)
        content.grid(row=1, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        self.connection_frame = tk.Frame(content, bg=COLORS["surface"], padx=20, pady=16, highlightthickness=1, highlightbackground=COLORS["line"])
        self.connection_frame.grid(row=0, column=0, sticky="ew")
        self.connection_label = tk.Label(
            self.connection_frame,
            text="Аккаунт не подключён",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 11),
        )
        self.connection_label.pack(side="left")
        self.login_button = ttk.Button(
            self.connection_frame,
            text="Войти в Telegram",
            style="Accent.TButton",
            command=self._open_login_window,
        )
        self.login_button.pack(side="right")

        self.main_frame = tk.Frame(content, bg=COLORS["surface"], padx=20, pady=18, highlightthickness=1, highlightbackground=COLORS["line"])
        self.main_frame.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(5, weight=1)
        self._build_message_form()
        self.main_frame.grid_remove()

        status_bar = tk.Frame(self.root, bg=COLORS["surface"], padx=24, pady=11, highlightthickness=1, highlightbackground=COLORS["line"])
        status_bar.grid(row=2, column=0, sticky="ew")
        status_bar.grid_columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            status_bar,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            anchor="w",
            font=("Segoe UI", 9),
            wraplength=560,
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

    def _build_message_form(self) -> None:
        self.main_frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            self.main_frame,
            text="Кому отправить",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 12),
        ).grid(row=0, column=0, sticky="w")

        chat_row = tk.Frame(self.main_frame, bg=COLORS["surface"])
        chat_row.grid(row=1, column=0, sticky="ew", pady=(8, 5))
        chat_row.grid_columnconfigure(0, weight=1)
        self.recipient_var = tk.StringVar()
        self.recipient_combo = ttk.Combobox(
            chat_row,
            textvariable=self.recipient_var,
            state="readonly",
            style="Messenger.TCombobox",
        )
        self.recipient_combo.grid(row=0, column=0, sticky="ew")
        self.recipient_combo.bind("<<ComboboxSelected>>", self._on_recipient_selected)
        self.load_chats_button = ttk.Button(
            chat_row,
            text="Обновить",
            style="Messenger.TButton",
            command=self._load_recipients,
        )
        self.load_chats_button.grid(row=0, column=1, padx=(8, 0))

        tk.Label(
            self.main_frame,
            text="Или найди человека по точному @username",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=2, column=0, sticky="w", pady=(10, 3))
        username_row = tk.Frame(self.main_frame, bg=COLORS["surface"])
        username_row.grid(row=3, column=0, sticky="ew")
        username_row.grid_columnconfigure(0, weight=1)
        self.username_var = tk.StringVar()
        self.username_entry = ttk.Entry(
            username_row,
            textvariable=self.username_var,
            style="Messenger.TEntry",
            font=("Consolas", 10),
        )
        self.username_entry.grid(row=0, column=0, sticky="ew")
        self.username_entry.bind("<Return>", lambda _event: self._resolve_username())
        self.find_user_button = ttk.Button(
            username_row,
            text="Найти",
            style="Messenger.TButton",
            command=self._resolve_username,
        )
        self.find_user_button.grid(row=0, column=1, padx=(8, 0))

        self.destination_label = tk.Label(
            self.main_frame,
            text="Получатель не выбран",
            bg="#EAF4F9",
            fg=COLORS["muted"],
            anchor="w",
            padx=10,
            pady=8,
            font=("Segoe UI", 9),
        )
        self.destination_label.grid(row=4, column=0, sticky="ew", pady=(12, 16))

        tk.Label(
            self.main_frame,
            text="Текст сообщения",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 12),
        ).grid(row=5, column=0, sticky="nw")
        self.message_text = tk.Text(
            self.main_frame,
            height=8,
            wrap="word",
            undo=True,
            bg="#FBFDFE",
            fg=COLORS["ink"],
            insertbackground=COLORS["accent_dark"],
            font=("Segoe UI", 11),
            relief="flat",
            padx=12,
            pady=10,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
            highlightcolor=COLORS["accent"],
        )
        self.message_text.grid(row=6, column=0, sticky="nsew", pady=(7, 13))
        self.message_text.bind("<<Modified>>", self._on_message_modified)

        send_row = tk.Frame(self.main_frame, bg=COLORS["surface"])
        send_row.grid(row=7, column=0, sticky="ew")
        send_row.grid_columnconfigure(0, weight=1)
        tk.Label(
            send_row,
            text="Проверь получателя перед отправкой.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")
        self.send_button = ttk.Button(
            send_row,
            text="Отправить сообщение",
            style="Accent.TButton",
            command=self._send_message,
            state="disabled",
        )
        self.send_button.grid(row=0, column=1, sticky="e")

    def _labeled_entry(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        show: str | None,
    ) -> ttk.Entry:
        frame = tk.Frame(parent, bg=COLORS["surface"])
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 8))
        frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            frame,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(frame, style="Messenger.TEntry", show=show)
        entry.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        return entry

    def _submit(
        self,
        coro,
        on_success: Callable[[Any], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        def complete(result: Any | Exception) -> None:
            if isinstance(result, Exception):
                on_error(result)
            else:
                on_success(result)

        try:
            self.worker.submit(coro, complete)
        except Exception as error:
            on_error(error)

    def _on_authorization_checked(self, authorized: bool) -> None:
        if authorized:
            self._on_login_success()
            return
        self.connection_label.configure(text="Аккаунт не подключён")
        self.login_button.grid()
        self.main_frame.grid_remove()
        self._set_status("Войди в Telegram, чтобы выбрать получателя.", "muted")
        if self._auto_open_login:
            self._auto_open_login = False
            self._open_login_window()

    def _open_login_window(self) -> None:
        if self._login_window is not None and self._login_window.winfo_exists():
            self._login_window.lift()
            return
        self._login_window = LoginWindow(self)

    def _on_login_window_closed(self, login_window: "LoginWindow") -> None:
        if self._login_window is login_window:
            self._login_window = None

    def _on_login_success(self) -> None:
        self._login_window = None
        self._show_message_form()
        self._load_recipients()

    def _show_message_form(self) -> None:
        self.login_button.grid_remove()
        self.connection_label.configure(text="Аккаунт подключён")
        self.main_frame.grid()
        self._set_status("Аккаунт подключён. Выбери одного человека.", "success")

    def _load_recipients(self) -> None:
        self.load_chats_button.configure(state="disabled")
        self._set_status("Загружаю личные переписки…", "muted")
        self._submit(
            self.service.list_recipients(),
            self._on_recipients_loaded,
            lambda error: self._show_operation_error(error, "dialogs"),
        )

    def _on_recipients_loaded(self, recipients: list[Recipient]) -> None:
        self.load_chats_button.configure(state="normal")
        self._recipient_by_label.clear()
        labels = []
        for recipient in recipients:
            label = recipient_label(recipient)
            if label in self._recipient_by_label:
                label = f"{label} · {recipient.id}"
            labels.append(label)
            self._recipient_by_label[label] = recipient
        self.recipient_combo.configure(values=labels)
        if not recipients:
            self._set_status("Личных переписок пока нет. Найди человека по @username.", "muted")
            return
        self._set_status(f"Загружено личных переписок: {len(recipients)}.", "success")

    def _on_recipient_selected(self, _event: tk.Event | None = None) -> None:
        self._selected_recipient = self._recipient_by_label.get(self.recipient_var.get())
        self._update_destination()
        self._refresh_send_button()

    def _resolve_username(self) -> None:
        username = self.username_var.get().strip()
        if not username:
            self._set_status("Введи точный @username человека.", "error")
            return
        self.find_user_button.configure(state="disabled")
        self._set_status("Ищу Telegram-аккаунт…", "muted")
        self._submit(
            self.service.resolve_username(username),
            self._on_username_resolved,
            lambda error: self._show_operation_error(error, "username"),
        )

    def _on_username_resolved(self, recipient: Recipient) -> None:
        self.find_user_button.configure(state="normal")
        label = recipient_label(recipient)
        if label in self._recipient_by_label and self._recipient_by_label[label].id != recipient.id:
            label = f"{label} · {recipient.id}"
        self._recipient_by_label[label] = recipient
        values = list(self.recipient_combo.cget("values"))
        if label not in values:
            values.append(label)
        self.recipient_combo.configure(values=values)
        self.recipient_var.set(label)
        self._selected_recipient = recipient
        self._update_destination()
        self._refresh_send_button()
        self._set_status("Получатель выбран. Проверь имя перед отправкой.", "success")

    def _update_destination(self) -> None:
        if self._selected_recipient is None:
            text = "Получатель не выбран"
        else:
            text = f"Будет отправлено: {recipient_label(self._selected_recipient)}"
        self.destination_label.configure(text=text)

    def _on_message_modified(self, _event: tk.Event | None = None) -> None:
        if self.message_text.edit_modified():
            self.message_text.edit_modified(False)
            self._refresh_send_button()

    def _refresh_send_button(self) -> None:
        message = self.message_text.get("1.0", "end-1c")
        can_send = bool(self._selected_recipient and message.strip()) and not self.controller.pending
        self.send_button.configure(state="normal" if can_send else "disabled")

    def _send_message(self) -> None:
        message = self.message_text.get("1.0", "end-1c")
        self.controller.send(self._selected_recipient, message)
        self._refresh_send_button()

    def _on_send_state(self, state: str, message: str) -> None:
        self._set_status(status_message(state, message), state)
        self._refresh_send_button()

    def _show_operation_error(self, error: Exception, action: str) -> None:
        message = self._translate_error(error, action)
        self._set_status(message, "error")
        if action == "dialogs":
            self.load_chats_button.configure(state="normal")
        elif action == "username":
            self.find_user_button.configure(state="normal")

    def _translate_error(self, error: Exception, action: str) -> str:
        if isinstance(error, TelegramServiceError):
            return {
                "Telegram could not send a login code. Check the phone number and try again.": "Не удалось отправить код. Проверь номер телефона.",
                "The Telegram login code was not accepted.": "Код Telegram не подошёл. Проверь его и попробуй ещё раз.",
                "The Telegram login code expired. Request a new code.": "Срок действия кода истёк. Запроси новый код.",
                "Telegram rejected the login request.": "Telegram отклонил вход. Проверь данные и попробуй ещё раз.",
                "The two-step verification password was not accepted.": "Пароль двухэтапной проверки не подошёл.",
                "Telegram rejected the two-step verification password.": "Telegram отклонил пароль двухэтапной проверки.",
                "That Telegram username could not be resolved.": "Не нашёл такой @username. Проверь написание и доступность аккаунта.",
                "Enter one complete Telegram @username.": "Введи один полный @username без пробелов.",
                "Choose a personal Telegram account, not a group or channel.": "Выбери личный аккаунт, а не группу или канал.",
            }.get(str(error), "Telegram не выполнил запрос. Проверь данные и подключение.")
        if action == "dialogs":
            return "Не удалось загрузить переписки. Проверь интернет и обнови список."
        if action == "username":
            return "Не удалось найти аккаунт. Проверь @username и подключение."
        if action == "password":
            return "Не удалось проверить пароль. Попробуй ещё раз."
        if action == "login":
            return "Не удалось выполнить вход. Проверь номер и подключение."
        return "Не удалось подключиться к Telegram. Проверь интернет и попробуй ещё раз."

    def _set_status(self, text: str, tone: str) -> None:
        colors = {
            "error": COLORS["error"],
            "failed": COLORS["error"],
            "unknown": COLORS["warning"],
            "sent": COLORS["success"],
            "success": COLORS["success"],
            "sending": COLORS["accent_dark"],
            "muted": COLORS["muted"],
        }
        self.status_label.configure(text=text, fg=colors.get(tone, COLORS["muted"]))

    def _poll_worker(self) -> None:
        if self._destroyed:
            return
        for callback, result in self.worker.drain():
            try:
                callback(result)
            except Exception:
                self._set_status("Не удалось обновить окно. Перезапусти приложение.", "error")
        if not self._destroyed:
            self.root.after(50, self._poll_worker)

    def _on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        if self._login_window is not None:
            self._login_window.destroy(notify=False)
            self._login_window = None
        try:
            self.worker.submit(self.service.disconnect(), lambda _result: self._finish_close())
        except Exception:
            self._finish_close()

    def _finish_close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        self.worker.close()
        self.root.destroy()


class LoginWindow:
    def __init__(self, app: MessengerWindow) -> None:
        self.app = app
        self.window = tk.Toplevel(app.root)
        self._closed = False
        self._pending = False
        self.window.title("Вход в Telegram")
        self.window.geometry("460x520")
        self.window.resizable(False, False)
        self.window.configure(bg=COLORS["background"])
        self.window.transient(app.root)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", lambda _event: self.close())

        self._build_widgets()
        self.window.update_idletasks()
        self.window.focus_set()

    def _build_widgets(self) -> None:
        self.window.grid_columnconfigure(0, weight=1)
        self.window.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self.window, bg=COLORS["ink"], padx=24, pady=18)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(
            header,
            text="ПОДКЛЮЧЕНИЕ АККАУНТА",
            bg=COLORS["ink"],
            fg="#79C7E8",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Вход в Telegram",
            bg=COLORS["ink"],
            fg=COLORS["surface"],
            font=("Segoe UI Semibold", 17),
        ).pack(anchor="w", pady=(5, 0))

        content = tk.Frame(self.window, bg=COLORS["surface"], padx=22, pady=20)
        content.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)
        content.grid_columnconfigure(0, weight=1)
        tk.Label(
            content,
            text="Код и пароль двухэтапной проверки вводятся только здесь.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=390,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))

        self.phone_frame, self.phone_entry = self._labeled_entry(
            content, 1, "Номер телефона", show=None
        )
        self.code_frame, self.code_entry = self._labeled_entry(
            content, 2, "Код из Telegram", show="•"
        )
        self.password_frame, self.password_entry = self._labeled_entry(
            content, 3, "Пароль двухэтапной проверки", show="•"
        )
        self.code_frame.grid_remove()
        self.password_frame.grid_remove()

        buttons = tk.Frame(content, bg=COLORS["surface"])
        buttons.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self.request_code_button = ttk.Button(
            buttons,
            text="Запросить код",
            style="Messenger.TButton",
            command=self._request_login_code,
        )
        self.request_code_button.pack(side="left")
        self.sign_in_button = ttk.Button(
            buttons,
            text="Войти",
            style="Accent.TButton",
            command=self._sign_in_code,
        )
        self.password_button = ttk.Button(
            buttons,
            text="Подтвердить пароль",
            style="Accent.TButton",
            command=self._sign_in_password,
        )
        self.cancel_button = ttk.Button(
            buttons,
            text="Отмена",
            style="Messenger.TButton",
            command=self.close,
        )
        self.cancel_button.pack(side="right")

        self.status_label = tk.Label(
            content,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=390,
            font=("Segoe UI", 9),
        )
        self.status_label.grid(row=5, column=0, sticky="ew", pady=(14, 0))

    def _labeled_entry(
        self,
        parent: tk.Widget,
        row: int,
        label: str,
        show: str | None,
    ) -> tuple[tk.Frame, ttk.Entry]:
        frame = tk.Frame(parent, bg=COLORS["surface"])
        frame.grid(row=row, column=0, sticky="ew", pady=(0, 9))
        frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            frame,
            text=label,
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        ).grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(
            frame,
            style="Messenger.TEntry",
            show=show,
            font=("Segoe UI", 10),
        )
        entry.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        return frame, entry

    def winfo_exists(self) -> bool:
        if self._closed:
            return False
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def lift(self) -> None:
        if self.winfo_exists():
            self.window.lift()
            self.window.focus_set()

    def _is_alive(self) -> bool:
        return self.winfo_exists()

    def _set_status(self, text: str, tone: str) -> None:
        colors = {
            "error": COLORS["error"],
            "success": COLORS["success"],
            "muted": COLORS["muted"],
        }
        self.status_label.configure(text=text, fg=colors.get(tone, COLORS["muted"]))

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for entry in (self.phone_entry, self.code_entry, self.password_entry):
            entry.configure(state=state)
        for button in (
            self.request_code_button,
            self.sign_in_button,
            self.password_button,
            self.cancel_button,
        ):
            button.configure(state=state)
        self._pending = busy

    def _submit(
        self,
        operation,
        status: str,
        action: str,
        on_success: Callable[[Any], None],
    ) -> None:
        self._set_busy(True)
        self._set_status(status, "muted")
        self.app._submit(
            operation,
            lambda result: self._on_operation_success(result, on_success),
            lambda error: self._on_operation_error(error, action),
        )

    def _on_operation_success(
        self,
        result: Any,
        on_success: Callable[[Any], None],
    ) -> None:
        if not self._is_alive():
            return
        self._set_busy(False)
        on_success(result)

    def _on_operation_error(self, error: Exception, action: str) -> None:
        if not self._is_alive():
            return
        self._set_busy(False)
        self._show_operation_error(error, action)

    def _request_login_code(self) -> None:
        phone = self.phone_entry.get().strip()
        if not phone:
            self._set_status("Введи номер телефона с кодом страны.", "error")
            return
        self._submit(
            self.app.service.request_login_code(phone),
            "Запрашиваю код входа…",
            "login",
            self._on_code_requested,
        )

    def _on_code_requested(self, _result: Any = None) -> None:
        self.code_frame.grid()
        self.sign_in_button.pack(side="left", padx=(8, 0))
        self.code_entry.focus_set()
        self._set_status("Код запрошен. Проверь сообщения в Telegram.", "success")

    def _sign_in_code(self) -> None:
        phone = self.phone_entry.get().strip()
        code = self.code_entry.get().strip()
        if not code:
            self._set_status("Введи код из Telegram.", "error")
            return
        self._submit(
            self.app.service.sign_in_code(phone, code),
            "Проверяю код…",
            "login",
            self._on_code_sign_in,
        )

    def _on_code_sign_in(self, result: str) -> None:
        self.code_entry.delete(0, "end")
        if result == "password_required":
            self.password_frame.grid()
            self.password_button.pack(side="left", padx=(8, 0))
            self.password_entry.focus_set()
            self._set_status("Нужен пароль двухэтапной проверки.", "muted")
            return
        self._finish_login()

    def _sign_in_password(self) -> None:
        password = self.password_entry.get()
        if not password:
            self._set_status("Введи пароль двухэтапной проверки.", "error")
            return
        self._submit(
            self.app.service.sign_in_password(password),
            "Проверяю пароль…",
            "password",
            lambda _result: self._finish_login(),
        )

    def _finish_login(self) -> None:
        self.code_entry.delete(0, "end")
        self.password_entry.delete(0, "end")
        self.destroy()
        self.app._on_login_success()

    def _show_operation_error(self, error: Exception, action: str) -> None:
        self._set_status(self.app._translate_error(error, action), "error")
        if action == "login":
            self.code_entry.delete(0, "end")
        elif action == "password":
            self.password_entry.delete(0, "end")

    def close(self) -> None:
        if self._pending:
            self._set_status("Дождись завершения текущего запроса.", "muted")
            return
        self.destroy()

    def destroy(self, notify: bool = True) -> None:
        if self._closed:
            return
        self._closed = True
        for entry in (self.phone_entry, self.code_entry, self.password_entry):
            try:
                entry.delete(0, "end")
            except tk.TclError:
                pass
        try:
            if self.window.winfo_exists():
                self.window.destroy()
        except tk.TclError:
            pass
        if notify:
            self.app._on_login_window_closed(self)


class CredentialSetupWindow:
    def __init__(
        self,
        root: tk.Tk,
        env_path,
        on_saved: Callable[[Settings], None],
        on_cancel: Callable[[], None],
    ) -> None:
        self.root = root
        self.env_path = env_path
        self.on_saved = on_saved
        self.on_cancel = on_cancel
        self._saving = False
        self._escape_binding: str | None = None

        root.title("Настройка Telegram API")
        root.geometry("520x440")
        root.minsize(480, 400)
        root.configure(bg=COLORS["background"])
        self._configure_styles()
        root.protocol("WM_DELETE_WINDOW", self._cancel)
        self._escape_binding = root.bind("<Escape>", self._on_escape)
        self._build_widgets()
        self._prefill()

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure(
            "Messenger.TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["ink"],
            padding=(9, 8),
            bordercolor=COLORS["line"],
        )
        style.configure(
            "Messenger.TButton",
            font=("Segoe UI", 10),
            padding=(12, 8),
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI Semibold", 11),
            padding=(14, 10),
            background=COLORS["accent"],
            foreground=COLORS["surface"],
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", "#A9C8D9"), ("active", COLORS["accent_dark"])],
            foreground=[("disabled", "#F7FAFC"), ("!disabled", COLORS["surface"])],
        )

    def _build_widgets(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)

        self.header = tk.Frame(self.root, bg=COLORS["ink"], padx=24, pady=18)
        self.header.grid(row=0, column=0, sticky="ew")
        header = self.header
        tk.Label(
            header,
            text="ПЕРВЫЙ ЗАПУСК",
            bg=COLORS["ink"],
            fg="#79C7E8",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Настройка Telegram API",
            bg=COLORS["ink"],
            fg=COLORS["surface"],
            font=("Segoe UI Semibold", 17),
        ).pack(anchor="w", pady=(5, 0))

        self.frame = tk.Frame(
            self.root,
            bg=COLORS["surface"],
            padx=24,
            pady=20,
            highlightthickness=1,
            highlightbackground=COLORS["line"],
        )
        self.frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=18)
        self.frame.grid_columnconfigure(0, weight=1)
        tk.Label(
            self.frame,
            text="Введи API ID и API Hash с my.telegram.org → API development tools.\n"
                 "Это ключи приложения; вход в аккаунт будет следующим шагом.",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            wraplength=440,
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))

        tk.Label(
            self.frame,
            text="API ID",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=1, column=0, sticky="w")
        self.api_id_entry = ttk.Entry(
            self.frame,
            style="Messenger.TEntry",
            font=("Segoe UI", 10),
        )
        self.api_id_entry.grid(row=2, column=0, sticky="ew", pady=(4, 10))
        self.api_id_entry.bind("<KeyRelease>", self._refresh_save_button)

        tk.Label(
            self.frame,
            text="API Hash",
            bg=COLORS["surface"],
            fg=COLORS["ink"],
            font=("Segoe UI Semibold", 10),
        ).grid(row=3, column=0, sticky="w")
        self.api_hash_entry = ttk.Entry(
            self.frame,
            style="Messenger.TEntry",
            show="•",
            font=("Segoe UI", 10),
        )
        self.api_hash_entry.grid(row=4, column=0, sticky="ew", pady=(4, 3))
        self.api_hash_entry.bind("<KeyRelease>", self._refresh_save_button)
        self.show_hash_var = tk.BooleanVar(self.root, value=False)
        ttk.Checkbutton(
            self.frame,
            text="Показать",
            variable=self.show_hash_var,
            command=self._toggle_hash,
        ).grid(row=5, column=0, sticky="w", pady=(0, 8))

        buttons = tk.Frame(self.frame, bg=COLORS["surface"])
        buttons.grid(row=6, column=0, sticky="ew", pady=(6, 0))
        self.save_button = ttk.Button(
            buttons,
            text="Сохранить и продолжить",
            style="Accent.TButton",
            command=self._save,
            state="disabled",
        )
        self.save_button.pack(side="left")
        self.cancel_button = ttk.Button(
            buttons,
            text="Отмена",
            style="Messenger.TButton",
            command=self._cancel,
        )
        self.cancel_button.pack(side="right")

        self.status_label = tk.Label(
            self.frame,
            text="",
            bg=COLORS["surface"],
            fg=COLORS["muted"],
            anchor="w",
            justify="left",
            wraplength=440,
            font=("Segoe UI", 9),
        )
        self.status_label.grid(row=7, column=0, sticky="ew", pady=(12, 0))

    def _prefill(self) -> None:
        api_id, api_hash = read_api_credentials(self.env_path)
        if api_id:
            self.api_id_entry.insert(0, api_id)
        if api_hash:
            self.api_hash_entry.insert(0, api_hash)
        self._refresh_save_button()

    def _toggle_hash(self) -> None:
        self.api_hash_entry.configure(show="" if self.show_hash_var.get() else "•")

    def _refresh_save_button(self, _event: tk.Event | None = None) -> None:
        try:
            validate_api_credentials(
                self.api_id_entry.get(),
                self.api_hash_entry.get(),
            )
        except CredentialError:
            enabled = False
        else:
            enabled = True
        self.save_button.configure(state="normal" if enabled and not self._saving else "disabled")

    def _set_status(self, text: str, tone: str) -> None:
        color = COLORS["error"] if tone == "error" else COLORS["muted"]
        self.status_label.configure(text=text, fg=color)

    def _set_busy(self, busy: bool) -> None:
        self._saving = busy
        self.api_id_entry.configure(state="disabled" if busy else "normal")
        self.api_hash_entry.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="disabled" if busy else "normal")
        self._refresh_save_button()

    def _credential_error_message(self, error: CredentialError) -> str:
        message = str(error)
        if "TELEGRAM_API_ID is set in the environment" in message:
            return "Переменная среды TELEGRAM_API_ID переопределяет .env. Исправь или удали её."
        if "TELEGRAM_API_HASH is set in the environment" in message:
            return "Переменная среды TELEGRAM_API_HASH переопределяет .env. Исправь или удали её."
        if "TELEGRAM_API_ID" in message and "must be an integer" in message:
            return "API ID должен быть положительным целым числом."
        if "TELEGRAM_API_HASH" in message and "32 hexadecimal" in message:
            return "API Hash должен содержать 32 шестнадцатеричных символа."
        if "TELEGRAM_API_ID" in message:
            return "Введи API ID."
        if "TELEGRAM_API_HASH" in message:
            return "Введи API Hash."
        return "Не удалось сохранить настройки. Проверь права на папку проекта."

    def _save(self) -> None:
        if self._saving:
            return
        api_id = self.api_id_entry.get().strip()
        api_hash = self.api_hash_entry.get().strip()
        try:
            validate_api_credentials(api_id, api_hash)
        except CredentialError as error:
            self._set_status(self._credential_error_message(error), "error")
            return

        self._set_busy(True)
        self._set_status("Сохраняю настройки…", "muted")
        self.root.update_idletasks()
        try:
            save_api_credentials(self.env_path, api_id, api_hash)
            settings = load_settings(self.env_path)
        except CredentialError as error:
            self._set_busy(False)
            self._set_status(self._credential_error_message(error), "error")
            return
        except ValueError:
            self._set_busy(False)
            self._set_status("Не удалось загрузить настройки Windows. Проверь LOCALAPPDATA.", "error")
            return
        except OSError:
            self._set_busy(False)
            self._set_status("Не удалось сохранить настройки. Проверь права на папку проекта.", "error")
            return

        self._set_busy(False)
        self._clear_fields()
        self._close_form()
        self.on_saved(settings)

    def _clear_fields(self) -> None:
        self.api_id_entry.delete(0, "end")
        self.api_hash_entry.delete(0, "end")

    def _close_form(self) -> None:
        if self._escape_binding:
            try:
                self.root.unbind("<Escape>", self._escape_binding)
            except tk.TclError:
                pass
            self._escape_binding = None
        self.header.destroy()
        self.frame.destroy()

    def _on_escape(self, _event: tk.Event | None = None) -> str:
        self._cancel()
        return "break"

    def _cancel(self) -> None:
        if self._saving:
            return
        self._clear_fields()
        self._close_form()
        self.on_cancel()
