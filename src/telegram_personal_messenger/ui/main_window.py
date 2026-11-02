"""Главное окно клиента: папки, список чатов и переписка."""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..async_worker import AsyncWorker
from ..config import Settings, save_session_string
from ..formatting import (
    chats_word,
    day_key,
    format_date_separator,
    preview,
)
from ..models import Account, Chat, MAX_MESSAGE_LENGTH, Message, SendOutcome
from ..state import ChatStore
from ..telegram_service import TelegramService
from .login import LoginView
from .media import load_photoimage
from .text import (
    account_title,
    chat_subtitle,
    error_text,
    message_counter,
    outcome_text,
    short_username,
)
from .theme import Theme
from .widgets import (
    Avatar,
    ChatRow,
    DateSeparator,
    EmptyState,
    FlatButton,
    FolderTabs,
    MessageBubble,
    ScrollableFrame,
    SearchBox,
)

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 60


class MainWindow:
    def __init__(
        self,
        root: tk.Tk,
        theme: Theme,
        service: TelegramService,
        worker: AsyncWorker,
        settings: Settings,
        env_path: Path,
    ) -> None:
        self.root = root
        self.theme = theme
        self.service = service
        self.worker = worker
        self.settings = settings
        self.env_path = env_path
        self.store = ChatStore()

        self._account: Account | None = None
        self.read_only = os.environ.get("TPM_READ_ONLY") == "1"
        self._shell_built = False
        self._avatar_paths: dict[int, Path] = {}
        self._avatar_photos: dict[tuple[int, int], tk.PhotoImage] = {}
        self._avatar_requested: set[int] = set()
        self._media_thumbs: dict[tuple[int, int], tk.PhotoImage] = {}
        self._media_requested: set[tuple[int, int]] = set()
        self._destroyed = False
        self._closing = False
        self._login_view: LoginView | None = None

        self._incoming: queue.Queue[Message] = queue.Queue()
        self._messages: list[Message] = []
        self._drafts: dict[int, str] = {}
        self._loaded_chat_id: int | None = None
        self._history_token = 0
        self._has_older = True
        self._loading_history = False
        self._loading_older = False
        self._bubbles: list[MessageBubble] = []
        self._send_pending = False
        self._reply_to: int | None = None
        self._editing: int | None = None
        self._loading_sidebar = False
        self._refresh_after_id: str | None = None
        self._resize_after_id: str | None = None
        self._status_after_id: str | None = None
        self._poll_worker_id: str | None = None
        self._poll_events_id: str | None = None

        self._configure_window()
        self.container = tk.Frame(root, bg=self.theme.palette.window)
        self.container.pack(fill="both", expand=True)

        root.protocol("WM_DELETE_WINDOW", self.close)
        self._show_loading("Подключаюсь к Telegram…", "Проверяю сохранённую сессию.")
        self._poll_worker()
        self._poll_events()
        self._bootstrap()

    # ── Запуск и авторизация ────────────────────────────────────────

    def _configure_window(self) -> None:
        p = self.theme.palette
        self.root.title("Telegram — личный клиент")
        self.root.configure(bg=p.window)
        self.root.minsize(900, 620)
        width, height = 1180, 760
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _bootstrap(self) -> None:
        self._show_loading("Подключаюсь к Telegram…", "Проверяю сохранённую сессию.")

        async def operation() -> Account | None:
            if not await self.service.is_authorized():
                return None
            return await self.service.get_me()

        self._submit(operation(), self._on_boot_ready, self._on_boot_error)

    def _on_boot_ready(self, account: Account | None) -> None:
        if self._destroyed or self._closing:
            return
        if account is None:
            self._show_login()
            return
        self._start_shell(account)

    def _on_boot_error(self, error: Exception) -> None:
        if self._destroyed:
            return
        self._show_error(
            "Не удалось подключиться",
            error_text(error),
            action_text="Повторить",
            action=self._bootstrap,
        )

    def _show_login(self) -> None:
        self._clear_container()
        self._login_view = LoginView(
            self.container,
            self.theme,
            self.service,
            self._submit,
            self._on_login_success,
        )
        self._login_view.pack(fill="both", expand=True)

    def _on_login_success(self) -> None:
        session = self.service.session_string()
        if session:
            try:
                save_session_string(self.env_path, session)
            except Exception:
                logger.warning("Не удалось сохранить обновлённую сессию в .env")
        self._login_view = None
        self._bootstrap()

    # ── Каркас главного окна ────────────────────────────────────────

    def _start_shell(self, account: Account) -> None:
        self._account = account
        self._clear_container()
        self._build_shell()
        self._shell_built = True
        try:
            self.service.start_listening(self._incoming.put)
        except Exception:
            logger.warning("Не удалось включить обработчик входящих сообщений")
        self._request_avatar(self._account.id, photo_available=True)
        self._load_sidebar(initial=True)

    def _build_shell(self) -> None:
        p = self.theme.palette
        self.shell = tk.Frame(self.container, bg=p.window)
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_rowconfigure(0, weight=1)
        self.shell.grid_columnconfigure(0, minsize=380)
        self.shell.grid_columnconfigure(1, weight=1)

        self.sidebar = tk.Frame(self.shell, bg=p.sidebar, width=380)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        self.sidebar.grid_columnconfigure(0, weight=1)
        self.sidebar.grid_rowconfigure(3, weight=1)

        self._build_sidebar_header()
        self._build_search()
        self._build_folder_tabs()
        self._build_chat_list()
        self._build_sidebar_footer()

        self.conversation = tk.Frame(self.shell, bg=p.window)
        self.conversation.grid(row=0, column=1, sticky="nsew")
        self.conversation.grid_rowconfigure(0, weight=1)
        self.conversation.grid_columnconfigure(0, weight=1)

        self.chat_stack = tk.Frame(self.conversation, bg=p.window)
        self.chat_stack.pack(fill="both", expand=True)
        self._build_chat_panel()
        self._show_empty_state()

    def _build_sidebar_header(self) -> None:
        p = self.theme.palette
        header = tk.Frame(self.sidebar, bg=p.sidebar, padx=16, pady=14)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        self.me_avatar = Avatar(header, self.theme, size=38, bg=p.sidebar)
        self.me_avatar.show(
            account_title(self._account),
            seed=self._account.id if self._account else "me",
        )
        self.me_avatar.grid(row=0, column=0, rowspan=2, padx=(0, 10))

        tk.Label(
            header,
            text="Telegram",
            bg=p.sidebar,
            fg=p.text,
            font=self.theme.font(13, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        self.header_status = tk.Label(
            header,
            text="Подключено",
            bg=p.sidebar,
            fg=p.green,
            font=self.theme.font(8),
            anchor="w",
        )
        self.header_status.grid(row=1, column=1, sticky="w")

        self.refresh_button = FlatButton(
            header,
            self.theme,
            "⟳",
            self._refresh,
            bg=p.sidebar,
            fg=p.muted,
            hover_bg=p.hover,
            hover_fg=p.text,
            font=self.theme.font(15),
            padx=8,
            pady=2,
        )
        self.refresh_button.grid(row=0, column=2, rowspan=2, sticky="e")

    def _build_search(self) -> None:
        p = self.theme.palette
        row = tk.Frame(self.sidebar, bg=p.sidebar)
        row.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 8))
        row.grid_columnconfigure(0, weight=1)
        self.search = SearchBox(row, self.theme, self._on_search_changed)
        self.search.grid(row=0, column=0, sticky="ew")

    def _build_folder_tabs(self) -> None:
        p = self.theme.palette
        row = tk.Frame(self.sidebar, bg=p.sidebar, padx=14, pady=8)
        row.grid(row=2, column=0, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        self.folder_tabs = FolderTabs(row, self.theme, self._on_folder_selected)
        self.folder_tabs.grid(row=0, column=0, sticky="ew")

    def _build_chat_list(self) -> None:
        p = self.theme.palette
        self.chat_list = ScrollableFrame(self.sidebar, self.theme, bg=p.sidebar)
        self.chat_list.grid(row=3, column=0, sticky="nsew")

    def _build_sidebar_footer(self) -> None:
        p = self.theme.palette
        border = tk.Frame(self.sidebar, bg=p.line, height=1)
        border.grid(row=4, column=0, sticky="ew")
        footer = tk.Frame(self.sidebar, bg=p.sidebar, padx=14, pady=10)
        footer.grid(row=5, column=0, sticky="ew")
        footer.grid_columnconfigure(1, weight=1)

        self.footer_avatar = Avatar(footer, self.theme, size=32, bg=p.sidebar)
        self.footer_avatar.show(
            account_title(self._account),
            seed=self._account.id if self._account else "me",
        )
        self.footer_avatar.grid(row=0, column=0, rowspan=2, padx=(0, 9))

        tk.Label(
            footer,
            text=account_title(self._account),
            bg=p.sidebar,
            fg=p.text_soft,
            font=self.theme.font(9, "bold"),
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        self.sidebar_status = tk.Label(
            footer,
            text="Готово",
            bg=p.sidebar,
            fg=p.muted,
            font=self.theme.font(8),
            anchor="w",
        )
        self.sidebar_status.grid(row=1, column=1, sticky="w")

    def _build_chat_panel(self) -> None:
        p = self.theme.palette
        self.chat_panel = tk.Frame(self.chat_stack, bg=p.window)
        self.chat_panel.grid_columnconfigure(0, weight=1)
        self.chat_panel.grid_rowconfigure(2, weight=1)

        header = tk.Frame(self.chat_panel, bg=p.panel, padx=18, pady=12)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        self.chat_avatar = Avatar(header, self.theme, size=42, bg=p.panel)
        self.chat_avatar.grid(row=0, column=0, rowspan=2, padx=(0, 12))

        self.chat_title = tk.Label(
            header,
            text="",
            bg=p.panel,
            fg=p.text,
            font=self.theme.font(12, "bold"),
            anchor="w",
        )
        self.chat_title.grid(row=0, column=1, sticky="w")
        self.chat_subtitle = tk.Label(
            header,
            text="",
            bg=p.panel,
            fg=p.muted,
            font=self.theme.font(8),
            anchor="w",
        )
        self.chat_subtitle.grid(row=1, column=1, sticky="w")

        self.reload_button = FlatButton(
            header,
            self.theme,
            "⟳",
            self._reload_history,
            bg=p.panel,
            fg=p.muted,
            hover_bg=p.hover,
            hover_fg=p.text,
            font=self.theme.font(15),
            padx=8,
            pady=2,
        )
        self.reload_button.grid(row=0, column=2, rowspan=2, sticky="e")

        line = tk.Frame(self.chat_panel, bg=p.line, height=1)
        line.grid(row=1, column=0, sticky="ew")

        self.message_area = ScrollableFrame(self.chat_panel, self.theme, bg=p.window)
        self.message_area.grid(row=2, column=0, sticky="nsew")
        self.message_area.canvas.bind(
            "<Configure>",
            self._on_message_area_resize,
            add="+",
        )

        self.chat_status = tk.Label(
            self.chat_panel,
            text="",
            bg=p.window,
            fg=p.muted,
            font=self.theme.font(9),
            anchor="w",
            padx=18,
        )
        self.chat_status.grid(row=3, column=0, sticky="ew", pady=(2, 0))

        composer = tk.Frame(self.chat_panel, bg=p.panel, padx=14, pady=10)
        composer.grid(row=4, column=0, sticky="ew")
        composer.grid_columnconfigure(0, weight=1)

        input_frame = tk.Frame(
            composer,
            bg=p.surface,
            highlightthickness=1,
            highlightbackground=p.line_soft,
            highlightcolor=p.accent,
        )
        input_frame.grid(row=0, column=0, sticky="ew")
        input_frame.grid_columnconfigure(0, weight=1)

        self.composer_text = tk.Text(
            input_frame,
            height=1,
            width=1,
            wrap="word",
            undo=True,
            bg=p.surface,
            fg=p.text,
            insertbackground=p.accent,
            selectbackground=p.active,
            selectforeground=p.white,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=self.theme.font(10),
            padx=12,
            pady=9,
            spacing1=1,
            spacing3=1,
        )
        self.composer_text.grid(row=0, column=0, sticky="ew")
        self.composer_text.bind("<Return>", self._on_composer_enter)
        self.composer_text.bind("<<Modified>>", self._on_composer_modified)
        self.composer_text.bind("<KeyRelease>", self._on_composer_key)

        self.send_button = FlatButton(
            composer,
            self.theme,
            "➤",
            self._send,
            bg=p.accent,
            fg=p.window,
            hover_bg=p.accent_dark,
            hover_fg=p.window,
            font=self.theme.font(14, "bold"),
            padx=14,
            pady=8,
        )
        self.send_button.grid(row=0, column=1, padx=(10, 0), sticky="se")

        hint_row = tk.Frame(composer, bg=p.panel)
        hint_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        hint_row.grid_columnconfigure(0, weight=1)
        self.composer_hint = tk.Label(
            hint_row,
            text="Enter — отправить · Shift+Enter — новая строка",
            bg=p.panel,
            fg=p.muted,
            font=self.theme.font(8),
            anchor="w",
        )
        self.composer_hint.grid(row=0, column=0, sticky="w")
        self.counter = tk.Label(
            hint_row,
            text=message_counter(0, MAX_MESSAGE_LENGTH),
            bg=p.panel,
            fg=p.muted,
            font=self.theme.font(8),
            anchor="e",
        )
        self.counter.grid(row=0, column=1, sticky="e")

        self._refresh_send_button()

    # ── Экраны-заглушки ────────────────────────────────────────────

    def _clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def _show_loading(self, title: str, subtitle: str) -> None:
        self._clear_container()
        EmptyState(
            self.container,
            self.theme,
            title,
            subtitle,
            icon="✈",
        ).pack(fill="both", expand=True)

    def _show_error(
        self,
        title: str,
        subtitle: str,
        *,
        action_text: str,
        action: Callable[[], None],
    ) -> None:
        self._clear_container()
        EmptyState(
            self.container,
            self.theme,
            title,
            subtitle,
            icon="!",
            action_text=action_text,
            action=action,
        ).pack(fill="both", expand=True)

    def _show_empty_state(
        self,
        title: str = "Выбери чат",
        subtitle: str = "Слева — переписки, папки и архив. Выбери чат, чтобы читать и писать.",
    ) -> None:
        self.chat_panel.pack_forget()
        for child in self.chat_stack.winfo_children():
            if child is not self.chat_panel:
                child.destroy()
        EmptyState(
            self.chat_stack,
            self.theme,
            title,
            subtitle,
            icon="✈",
        ).pack(fill="both", expand=True)

    def _show_chat_panel(self) -> None:
        for child in self.chat_stack.winfo_children():
            if child is not self.chat_panel:
                child.destroy()
        self.chat_panel.pack(fill="both", expand=True)

    def _show_conversation_error(
        self,
        title: str,
        subtitle: str,
        action: Callable[[], None],
    ) -> None:
        self.chat_panel.pack_forget()
        for child in self.chat_stack.winfo_children():
            if child is not self.chat_panel:
                child.destroy()
        EmptyState(
            self.chat_stack,
            self.theme,
            title,
            subtitle,
            icon="!",
            action_text="Повторить",
            action=action,
        ).pack(fill="both", expand=True)

    # ── Загрузка списка чатов ──────────────────────────────────────

    def _refresh(self) -> None:
        self._load_sidebar(initial=False)

    def _load_sidebar(self, initial: bool) -> None:
        if self._loading_sidebar or self._destroyed:
            return
        self._loading_sidebar = True
        self.refresh_button.set_enabled(False)
        self._set_status("Обновляю чаты…", "muted")

        async def load() -> tuple[list, list[Chat]]:
            folders, chats = await asyncio.gather(
                self.service.list_folders(),
                self.service.list_chats(),
            )
            return folders, chats

        self._submit(
            load(),
            lambda result: self._on_sidebar_loaded(result),
            lambda error: self._on_sidebar_error(error, initial),
        )

    def _on_sidebar_loaded(self, result: tuple[list, list[Chat]]) -> None:
        if self._destroyed or self._closing:
            return
        self._loading_sidebar = False
        self.refresh_button.set_enabled(True)
        folders, chats = result
        self.store.load(chats, folders)
        self._render_folders()
        self._render_chat_list()

        count = len(chats)
        self._set_status(f"Загружено: {count} {chats_word(count)}", "success")

        if self.store.selected_id is not None:
            self._update_chat_header()
        else:
            visible = self.store.visible_chats()
            if visible:
                self._open_chat(visible[0].id)
                return
            self._show_empty_state(
                "Чатов пока нет",
                "Когда появятся переписки, они появятся здесь.",
            )

    def _on_sidebar_error(self, error: Exception, initial: bool) -> None:
        if self._destroyed or self._closing:
            return
        self._loading_sidebar = False
        self.refresh_button.set_enabled(True)
        message = error_text(error)
        self._set_status(message, "error")
        if initial or self.store.selected_id is None:
            self._show_conversation_error(
                "Не удалось загрузить чаты",
                message,
                self._refresh,
            )
        else:
            self._set_chat_status(message, "error")

    # ── Отрисовка списка чатов ─────────────────────────────────────

    def _render_folders(self) -> None:
        self.folder_tabs.set_folders(
            self.store.folders,
            self.store.folder_counts(),
            self.store.folder_key,
        )

    def _render_chat_list(self, reset_scroll: bool = False) -> None:
        position = 0.0 if reset_scroll else self.chat_list.yview()[0]
        self.chat_list.clear(reset_scroll=reset_scroll)

        query = self.store.query.strip()
        if query.startswith("@") and len(query) > 1:
            self._build_search_action(query)

        visible = self.store.visible_chats()
        if not visible and not (query.startswith("@") and len(query) > 1):
            if query:
                text = "Ничего не найдено"
            elif self.store.chats:
                text = "В этой папке пусто"
            else:
                text = "Чатов пока нет"
            label = tk.Label(
                self.chat_list.inner,
                text=text,
                bg=self.theme.palette.sidebar,
                fg=self.theme.palette.muted,
                font=self.theme.font(9),
                pady=30,
            )
            label.pack(fill="x")
            self.chat_list.bind_wheel(label)

        for chat in visible:
            photo = self._photo(chat.id, 46)
            row = ChatRow(
                self.chat_list.inner,
                self.theme,
                chat,
                selected=chat.id == self.store.selected_id,
                on_click=self._open_chat,
                scroll=self.chat_list,
                photo=photo,
            )
            row.pack(fill="x")
            if chat.photo_available:
                self._request_avatar(chat.id, photo_available=True)

        self.chat_list.update_idletasks()
        if not reset_scroll:
            self.chat_list.canvas.yview_moveto(position)

    def _build_search_action(self, query: str) -> None:
        p = self.theme.palette
        row = tk.Frame(self.chat_list.inner, bg=p.sidebar_alt, cursor="hand2")
        row.pack(fill="x")
        inner = tk.Frame(row, bg=p.sidebar_alt, padx=14, pady=10)
        inner.pack(fill="x")
        tk.Label(
            inner,
            text=f"Найти @{short_username(query)}",
            bg=p.sidebar_alt,
            fg=p.accent,
            font=self.theme.font(9, "bold"),
            anchor="w",
            cursor="hand2",
        ).pack(fill="x")
        tk.Label(
            inner,
            text="Открыть личный диалог по @username",
            bg=p.sidebar_alt,
            fg=p.muted,
            font=self.theme.font(8),
            anchor="w",
            cursor="hand2",
        ).pack(fill="x")
        for widget in (row, inner, *inner.winfo_children()):
            widget.bind(
                "<Button-1>",
                lambda _event: self._resolve_username(query),
                add="+",
            )
        self.chat_list.bind_wheel(row)

    # ── Выбор чата и история ───────────────────────────────────────

    def _open_chat(self, chat_id: int) -> None:
        chat = self.store.chat(chat_id)
        if chat is None or self._destroyed:
            return
        self._save_draft()
        self.store.select(chat_id)
        self._render_chat_list()
        self._show_chat_panel()
        self._update_chat_header()

        self._history_token += 1
        token = self._history_token
        self._loaded_chat_id = chat_id
        self._messages = []
        self._reply_to = None
        self._editing = None
        self._has_older = True
        self._loading_history = True
        self._loading_older = False
        self._render_messages()
        self._restore_draft(chat_id)
        self.composer_text.focus_set()
        self._load_history(chat_id, token, initial=True)

    def _load_history(self, chat_id: int, token: int, initial: bool) -> None:
        self._submit(
            self.service.get_messages(chat_id, limit=HISTORY_LIMIT),
            lambda messages: self._on_history(chat_id, token, messages, initial),
            lambda error: self._on_history_error(chat_id, token, error),
        )

    def _on_history(
        self,
        chat_id: int,
        token: int,
        messages: list[Message],
        initial: bool,
    ) -> None:
        if (
            self._destroyed
            or chat_id != self._loaded_chat_id
            or token != self._history_token
        ):
            return

        if initial:
            self._loading_history = False
            self._messages = list(messages)
            self._has_older = len(messages) >= HISTORY_LIMIT
            self._render_messages(scroll_bottom=True)
            self._mark_read(chat_id)
            return

        self._loading_older = False
        known = {message.id for message in self._messages}
        older = [message for message in messages if message.id not in known]
        if older:
            self._messages = older + self._messages
        self._has_older = len(messages) >= HISTORY_LIMIT
        self._render_messages()

    def _on_history_error(self, chat_id: int, token: int, error: Exception) -> None:
        if (
            self._destroyed
            or chat_id != self._loaded_chat_id
            or token != self._history_token
        ):
            return
        self._loading_history = False
        self._loading_older = False
        message = error_text(error)
        self._set_chat_status(message, "error")
        self.message_area.clear()
        label = tk.Label(
            self.message_area.inner,
            text=message,
            bg=self.theme.palette.window,
            fg=self.theme.palette.red,
            font=self.theme.font(9),
            wraplength=420,
            justify="center",
            pady=40,
        )
        label.pack(fill="x")
        self.message_area.bind_wheel(label)

    def _load_older(self) -> None:
        if (
            self._loading_older
            or not self._has_older
            or self._loaded_chat_id is None
            or not self._messages
            or self._destroyed
        ):
            return
        self._loading_older = True
        oldest = min(message.id for message in self._messages)
        chat_id = self._loaded_chat_id
        token = self._history_token
        self._submit(
            self.service.get_messages(
                chat_id,
                limit=HISTORY_LIMIT,
                offset_id=oldest,
            ),
            lambda messages: self._on_history(chat_id, token, messages, initial=False),
            lambda error: self._on_older_error(chat_id, token, error),
        )

    def _on_older_error(self, chat_id: int, token: int, error: Exception) -> None:
        if (
            self._destroyed
            or chat_id != self._loaded_chat_id
            or token != self._history_token
        ):
            return
        self._loading_older = False
        self._set_chat_status(error_text(error), "error")

    def _reload_history(self) -> None:
        if self._loaded_chat_id is None:
            return
        self._open_chat(self._loaded_chat_id)

    def _mark_read(self, chat_id: int) -> None:
        if self.read_only:
            return
        if self.store.mark_read(chat_id):
            self._render_chat_list()
        self._submit(
            self.service.mark_read(chat_id),
            lambda _result: None,
            lambda _error: None,
        )

    # ── Отрисовка сообщений ────────────────────────────────────────

    def _render_messages(self, scroll_bottom: bool = False) -> None:
        if self._loaded_chat_id is None:
            return
        p = self.theme.palette
        previous_position = self.message_area.yview()[0]
        self.message_area.clear()
        self._bubbles = []

        if self._loading_history:
            label = tk.Label(
                self.message_area.inner,
                text="Загружаю сообщения…",
                bg=p.window,
                fg=p.muted,
                font=self.theme.font(9),
                pady=40,
            )
            label.pack(fill="x")
            self.message_area.bind_wheel(label)
            return

        chat = self.store.chat(self._loaded_chat_id)
        if chat is None:
            return

        if not self._messages:
            label = tk.Label(
                self.message_area.inner,
                text="Сообщений пока нет.\nНапиши первым.",
                bg=p.window,
                fg=p.muted,
                font=self.theme.font(9),
                justify="center",
                pady=40,
            )
            label.pack(fill="x")
            self.message_area.bind_wheel(label)
            return

        if self._has_older:
            load_more = FlatButton(
                self.message_area.inner,
                self.theme,
                "Загрузить ещё",
                self._load_older,
                bg=p.surface,
                fg=p.accent,
                hover_bg=p.hover,
                hover_fg=p.text,
                font=self.theme.font(9),
                padx=14,
                pady=6,
            )
            load_more.pack(pady=8)
            self.message_area.bind_wheel(load_more)

        previous_day = None
        previous_sender: str | None = None
        wraplength = self._bubble_wraplength()
        for message in self._messages:
            day = day_key(message.date)
            if day != previous_day:
                separator = DateSeparator(
                    self.message_area.inner,
                    self.theme,
                    format_date_separator(message.date),
                )
                separator.pack(fill="x")
                self.message_area.bind_wheel(separator)
                previous_day = day
                previous_sender = None

            show_sender = (
                chat.is_group
                and not message.out
                and bool(message.sender_name)
                and message.sender_name != previous_sender
            )
            media_photo = None
            if message.media_kind in ("photo", "video"):
                media_photo = self._media_thumb(message.chat_id, message.id)
            bubble = MessageBubble(
                self.message_area.inner,
                self.theme,
                message,
                show_sender=show_sender,
                wraplength=wraplength,
                scroll=self.message_area,
                media_photo=media_photo,
                on_action=self._on_message_action,
            )
            bubble.pack(fill="x")
            self._bubbles.append(bubble)
            previous_sender = None if message.out else message.sender_name
            if message.media_kind in ("photo", "video"):
                self._request_media_thumb(
                    message.chat_id,
                    message.id,
                    message.media_kind,
                )

        self.message_area.update_idletasks()
        if scroll_bottom:
            self.message_area.scroll_to_bottom()
        elif previous_position > 0:
            self.message_area.move_to(previous_position)

    def _bubble_wraplength(self) -> int:
        width = self.message_area.canvas.winfo_width()
        if width <= 10:
            width = 760
        return max(280, int(width * 0.62))

    def _on_message_area_resize(self, _event: tk.Event) -> None:
        if self._resize_after_id is not None:
            try:
                self.root.after_cancel(self._resize_after_id)
            except tk.TclError:
                pass
        self._resize_after_id = self.root.after(120, self._apply_bubble_width)

    def _apply_bubble_width(self) -> None:
        self._resize_after_id = None
        if self._destroyed:
            return
        wraplength = self._bubble_wraplength()
        for bubble in self._bubbles:
            bubble.set_wraplength(wraplength)

    # ── Ввод и отправка ────────────────────────────────────────────

    def _on_composer_enter(self, event: tk.Event) -> str | None:
        if getattr(event, "state", 0) & 0x0001:
            return None
        self._send()
        return "break"

    def _on_composer_modified(self, _event: tk.Event) -> None:
        if self.composer_text.edit_modified():
            self.composer_text.edit_modified(False)
            self._update_composer()

    def _on_composer_key(self, _event: tk.Event) -> None:
        self._update_composer()

    def _update_composer(self) -> None:
        text = self.composer_text.get("1.0", "end-1c")
        line_count = int(self.composer_text.index("end-1c").split(".")[0])
        height = max(1, min(6, line_count))
        if int(self.composer_text.cget("height")) != height:
            self.composer_text.configure(height=height)
        self.counter.configure(
            text=message_counter(len(text), MAX_MESSAGE_LENGTH),
            fg=(
                self.theme.palette.red
                if len(text) > MAX_MESSAGE_LENGTH
                else self.theme.palette.muted
            ),
        )
        self._refresh_send_button()

    def _refresh_send_button(self) -> None:
        if not hasattr(self, "send_button"):
            return
        text = self.composer_text.get("1.0", "end-1c") if hasattr(self, "composer_text") else ""
        can_send = (
            self.store.selected_id is not None
            and bool(text.strip())
            and len(text) <= MAX_MESSAGE_LENGTH
            and not self._send_pending
        )
        self.send_button.set_enabled(can_send)

    def _send(self) -> None:
        if self.read_only:
            self._set_chat_status("Режим только чтения: отправка отключена.", "warning")
            return
        if self._send_pending or self._destroyed:
            return
        chat_id = self.store.selected_id
        if chat_id is None:
            return
        text = self.composer_text.get("1.0", "end-1c")
        if not text.strip():
            self._set_chat_status("Сначала введи текст сообщения.", "error")
            return
        if len(text) > MAX_MESSAGE_LENGTH:
            self._set_chat_status(
                "Сообщение длиннее 4096 символов. Telegram не принимает такие сообщения.",
                "error",
            )
            return

        self._send_pending = True
        self._refresh_send_button()

        if self._editing is not None:
            editing_id = self._editing
            self._submit(
                self.service.edit_message(chat_id, editing_id, text),
                lambda edited: self._on_edit_done(chat_id, editing_id, edited),
                lambda error: self._on_send_error(chat_id, error),
            )
            return

        reply_to = self._reply_to
        self._submit(
            self.service.send_message(chat_id, text, reply_to=reply_to),
            lambda outcome: self._on_send_done(chat_id, text, outcome),
            lambda error: self._on_send_error(chat_id, error),
        )

    def _on_edit_done(
        self,
        chat_id: int,
        editing_id: int,
        edited: Message | None,
    ) -> None:
        if self._destroyed:
            return
        self._send_pending = False
        self._editing = None
        self._refresh_send_button()
        if edited is not None and chat_id == self._loaded_chat_id:
            self._messages = [
                edited if message.id == editing_id else message
                for message in self._messages
            ]
            self._render_messages()
        if chat_id == self.store.selected_id:
            self.composer_text.delete("1.0", "end")
            self._update_composer()
            self._set_chat_status("Сообщение изменено.", "success")

    def _on_send_done(self, chat_id: int, text: str, outcome: SendOutcome) -> None:
        if self._destroyed:
            return
        self._send_pending = False
        self._refresh_send_button()

        if outcome.kind == "sent":
            self._drafts.pop(chat_id, None)
            self._reply_to = None
            message = outcome.sent_message
            if message is None:
                message = Message(
                    id=0,
                    chat_id=chat_id,
                    text=text,
                    date=datetime.now(timezone.utc),
                    out=True,
                )
            if chat_id == self._loaded_chat_id:
                self._append_message(message)
                self.composer_text.delete("1.0", "end")
                self._update_composer()
            self.store.apply_message(message)
            self._render_chat_list()
            if chat_id == self.store.selected_id:
                self._set_chat_status("Сообщение отправлено.", "success")
            return

        self._set_chat_status(outcome_text(outcome), outcome_tone(outcome))
        if chat_id == self.store.selected_id:
            self.composer_text.focus_set()

    def _on_send_error(self, chat_id: int, error: Exception) -> None:
        if self._destroyed:
            return
        self._send_pending = False
        self._refresh_send_button()
        if chat_id == self.store.selected_id:
            self._set_chat_status(error_text(error), "error")
            self.composer_text.focus_set()

    def _save_draft(self) -> None:
        if self._loaded_chat_id is None or not hasattr(self, "composer_text"):
            return
        text = self.composer_text.get("1.0", "end-1c")
        if text.strip():
            self._drafts[self._loaded_chat_id] = text
        else:
            self._drafts.pop(self._loaded_chat_id, None)

    def _restore_draft(self, chat_id: int) -> None:
        if not hasattr(self, "composer_text"):
            return
        self.composer_text.delete("1.0", "end")
        text = self._drafts.get(chat_id, "")
        if text:
            self.composer_text.insert("1.0", text)
            self.composer_text.mark_set("insert", "end-1c")
        self._update_composer()

    def _append_message(self, message: Message) -> None:
        if message.chat_id != self._loaded_chat_id:
            return
        if message.id and any(existing.id == message.id for existing in self._messages):
            return
        at_bottom = self.message_area.yview()[1] >= 0.98
        self._messages.append(message)
        self._render_messages(scroll_bottom=at_bottom or message.out)

    # ── Входящие и поиск ───────────────────────────────────────────

    def _poll_events(self) -> None:
        self._poll_events_id = None
        if self._destroyed:
            return
        while True:
            try:
                message = self._incoming.get_nowait()
            except queue.Empty:
                break
            self._handle_incoming(message)
        if not self._destroyed:
            self._poll_events_id = self.root.after(120, self._poll_events)

    def _handle_incoming(self, message: Message) -> None:
        if message.chat_id == self._loaded_chat_id:
            self._append_message(message)
            self.store.apply_message(message)
            self._render_chat_list()
            self._mark_read(message.chat_id)
            return

        updated = self.store.apply_message(message)
        if updated:
            self._render_folders()
            self._render_chat_list()
            self._set_status("Новое сообщение", "muted")
            return
        self._schedule_sidebar_refresh()

    def _schedule_sidebar_refresh(self) -> None:
        if self._refresh_after_id is not None or self._destroyed:
            return
        self._refresh_after_id = self.root.after(700, self._refresh_later)

    def _refresh_later(self) -> None:
        self._refresh_after_id = None
        self._load_sidebar(initial=False)

    def _on_search_changed(self, _query: str) -> None:
        self.store.set_query(self.search.get())
        self._render_chat_list(reset_scroll=True)

    def _on_folder_selected(self, key: str) -> None:
        self.store.set_folder(key)
        self._render_folders()
        self._render_chat_list(reset_scroll=True)

    def _resolve_username(self, query: str) -> None:
        value = query.strip()
        if not value:
            return
        self._set_status(f"Ищу @{short_username(value)}…", "muted")

        def done(chat: Chat) -> None:
            if self._destroyed:
                return
            self.store.add_chat(chat)
            self.store.set_folder("all")
            self.store.set_query("")
            self.search.set_query("")
            self._render_folders()
            self._render_chat_list()
            self._open_chat(chat.id)
            self._set_status(f"Найден @{short_username(value)}", "success")

        def failed(error: Exception) -> None:
            if not self._destroyed:
                self._set_status(error_text(error), "error")

        self._submit(self.service.resolve_username(value), done, failed)

    # ── Общие помощники ────────────────────────────────────────────

    def _update_chat_header(self) -> None:
        chat = self.store.selected
        if chat is None:
            return
        p = self.theme.palette
        self.chat_avatar.show(chat.title, seed=chat.id)
        photo = self._photo(chat.id, 42)
        if photo is not None:
            self.chat_avatar.show_photo(photo)
        self.chat_title.configure(text=preview(chat.title, 40))
        self.chat_subtitle.configure(text=chat_subtitle(chat))
        self.chat_avatar.set_background(p.panel)
        self._refresh_send_button()

    # ── Аватарки ─────────────────────────────────────────────────────

    def _avatar_dir(self) -> Path:
        return self.settings.session_path.parent / "avatars"

    def _photo(self, chat_id: int, size: int) -> tk.PhotoImage | None:
        key = (chat_id, size)
        photo = self._avatar_photos.get(key)
        if photo is not None:
            return photo
        file_path = self._avatar_paths.get(chat_id)
        if file_path is None:
            return None
        photo = load_photoimage(file_path, size=size, circular=True)
        if photo is not None:
            self._avatar_photos[key] = photo
        return photo

    def _request_avatar(self, chat_id: int, *, photo_available: bool = True) -> None:
        if (
            not photo_available
            or chat_id in self._avatar_requested
            or chat_id in self._avatar_paths
            or len(self._avatar_requested) >= 12
        ):
            return
        self._avatar_requested.add(chat_id)
        avatar_dir = self._avatar_dir()
        try:
            avatar_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self._avatar_requested.discard(chat_id)
            return
        file_path = avatar_dir / f"{chat_id}.jpg"
        self._submit(
            self.service.download_avatar(chat_id, file=str(file_path)),
            lambda result: self._on_avatar_loaded(chat_id, result),
            lambda _error: self._avatar_requested.discard(chat_id),
        )

    def _on_avatar_loaded(self, chat_id: int, result: Any) -> None:
        self._avatar_requested.discard(chat_id)
        if not result:
            return
        self._avatar_paths[chat_id] = Path(result)
        for size in (32, 38, 42, 46):
            self._avatar_photos.pop((chat_id, size), None)
        self._render_chat_list()
        if self.store.selected_id == chat_id:
            self._update_chat_header()
        me_id = self._account.id if self._account is not None else None
        if chat_id == me_id:
            self._apply_me_avatar()

    def _apply_me_avatar(self) -> None:
        if self._account is None or not hasattr(self, "me_avatar"):
            return
        photo = self._photo(self._account.id, 38)
        if photo is not None:
            self.me_avatar.show_photo(photo)
        footer_photo = self._photo(self._account.id, 32)
        if footer_photo is not None:
            self.footer_avatar.show_photo(footer_photo)

    # ── Медиа-превью ─────────────────────────────────────────────────

    def _media_thumb(self, chat_id: int, message_id: int) -> tk.PhotoImage | None:
        return self._media_thumbs.get((chat_id, message_id))

    def _request_media_thumb(
        self,
        chat_id: int,
        message_id: int,
        media_kind: str | None,
    ) -> None:
        if media_kind not in ("photo", "video"):
            return
        key = (chat_id, message_id)
        if key in self._media_requested or key in self._media_thumbs:
            return
        if len(self._media_requested) >= 24:
            return
        self._media_requested.add(key)
        self._submit(
            self.service.download_media(chat_id, message_id, thumb=0),
            lambda result: self._on_media_thumb(chat_id, message_id, result),
            lambda _error: self._media_requested.discard(key),
        )

    def _on_media_thumb(self, chat_id: int, message_id: int, result: Any) -> None:
        self._media_requested.discard((chat_id, message_id))
        if result is None:
            return
        photo = load_photoimage(result, size=260)
        if photo is None:
            return
        self._media_thumbs[(chat_id, message_id)] = photo
        if self._loaded_chat_id == chat_id:
            self._render_messages()

    # ── Действия с сообщениями ──────────────────────────────────────

    def _on_message_action(self, action: str, message: Message) -> None:
        if action == "reply":
            self._reply_to = message.id
            self._editing = None
            self._set_chat_status(f"Ответ на сообщение #{message.id}", "muted")
            self.composer_text.focus_set()
        elif action == "edit":
            self._editing = message.id
            self._reply_to = None
            self.composer_text.delete("1.0", "end")
            self.composer_text.insert("1.0", message.text)
            self.composer_text.mark_set("insert", "end-1c")
            self._update_composer()
            self._set_chat_status("Редактирование сообщения", "muted")
            self.composer_text.focus_set()
        elif action == "delete":
            self._submit(
                self.service.delete_message(message.chat_id, message.id),
                lambda _result: self._on_delete_done(message.chat_id, message.id),
                lambda error: self._set_chat_status(error_text(error), "error"),
            )
        elif action == "pin":
            self._submit(
                self.service.pin_message(message.chat_id, message.id),
                lambda _result: self._set_chat_status(
                    "Сообщение закреплено.",
                    "success",
                ),
                lambda error: self._set_chat_status(error_text(error), "error"),
            )
        elif action == "save":
            self._submit(
                self.service.forward_to_saved(message.chat_id, [message.id]),
                lambda _result: self._set_chat_status(
                    "Сохранено в Избранное.",
                    "success",
                ),
                lambda error: self._set_chat_status(error_text(error), "error"),
            )

    def _on_delete_done(self, chat_id: int, message_id: int) -> None:
        if self._destroyed:
            return
        if chat_id == self._loaded_chat_id:
            self._messages = [
                message for message in self._messages if message.id != message_id
            ]
            self._render_messages()
        if chat_id == self.store.selected_id:
            self._set_chat_status("Сообщение удалено.", "success")

    def _set_status(self, text: str, tone: str) -> None:
        if not hasattr(self, "sidebar_status"):
            return
        colors = {
            "error": self.theme.palette.red,
            "success": self.theme.palette.green,
            "warning": self.theme.palette.yellow,
            "muted": self.theme.palette.muted,
        }
        self.sidebar_status.configure(
            text=preview(text, 70),
            fg=colors.get(tone, self.theme.palette.muted),
        )

    def _set_chat_status(self, text: str, tone: str) -> None:
        if not hasattr(self, "chat_status"):
            return
        colors = {
            "error": self.theme.palette.red,
            "success": self.theme.palette.green,
            "warning": self.theme.palette.yellow,
            "muted": self.theme.palette.muted,
        }
        self.chat_status.configure(
            text=preview(text, 120),
            fg=colors.get(tone, self.theme.palette.muted),
        )
        if self._status_after_id is not None:
            try:
                self.root.after_cancel(self._status_after_id)
            except tk.TclError:
                pass
        self._status_after_id = self.root.after(7000, self._clear_chat_status)

    def _clear_chat_status(self) -> None:
        self._status_after_id = None
        if not self._destroyed and hasattr(self, "chat_status"):
            self.chat_status.configure(text="")

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
        except Exception as exc:
            on_error(exc)

    def _poll_worker(self) -> None:
        self._poll_worker_id = None
        if self._destroyed:
            return
        for callback, result in self.worker.drain():
            try:
                callback(result)
            except Exception:
                logger.exception("Ошибка в обработчике результата")
        if not self._destroyed:
            self._poll_worker_id = self.root.after(40, self._poll_worker)

    # ── Закрытие ───────────────────────────────────────────────────

    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._set_status("Отключаюсь…", "muted")
        try:
            self.worker.submit(
                self.service.disconnect(),
                lambda _result: self._finish_close(),
            )
        except Exception:
            self._finish_close()

    def _finish_close(self) -> None:
        if self._destroyed:
            return
        self._destroyed = True
        for attribute in (
            "_poll_worker_id",
            "_poll_events_id",
            "_refresh_after_id",
            "_resize_after_id",
            "_status_after_id",
        ):
            after_id = getattr(self, attribute, None)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        try:
            self.worker.close()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def outcome_tone(outcome: SendOutcome) -> str:
    if outcome.kind == "unknown":
        return "warning"
    return "error"
