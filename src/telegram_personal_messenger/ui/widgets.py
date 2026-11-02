"""Переиспользуемые виджеты интерфейса.

Всё оформление собрано здесь, чтобы главное окно описывало сценарии,
а не занималось рисованием рамок и аватарок.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ..formatting import (
    avatar_color,
    format_chat_time,
    format_message_time,
    initials,
    preview,
    unread_text,
)
from ..models import Chat, Folder, Message
from .text import last_message_line
from .theme import Theme


class ScrollableFrame(tk.Frame):
    """Вертикально прокручиваемая область с внутренним фреймом."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        bg: str | None = None,
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        color = bg or self.palette.window
        super().__init__(parent, bg=color)

        self.canvas = tk.Canvas(
            self,
            bg=color,
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Vertical.TScrollbar",
        )
        self.inner = tk.Frame(self.canvas, bg=color)
        self._window = self.canvas.create_window(
            (0, 0),
            window=self.inner,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_wheel(self.canvas)

    def clear(self, reset_scroll: bool = True) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        if reset_scroll:
            self.canvas.yview_moveto(0)

    def scroll_to_bottom(self) -> None:
        self.update_idletasks()
        self.canvas.yview_moveto(1.0)

    def scroll_to_top(self) -> None:
        self.canvas.yview_moveto(0.0)

    def yview(self) -> tuple[float, float]:
        return self.canvas.yview()

    def move_to(self, fraction: float) -> None:
        self.update_idletasks()
        self.canvas.yview_moveto(fraction)

    def bind_wheel(self, widget: tk.Misc) -> None:
        """Прокрутка колесом при наведении на дочерний виджет."""

        self._bind_wheel(widget)
        for child in widget.winfo_children():
            self.bind_wheel(child)

    def _bind_wheel(self, widget: tk.Misc) -> None:
        widget.bind("<MouseWheel>", self._on_wheel, add="+")
        widget.bind("<Button-4>", self._on_wheel, add="+")
        widget.bind("<Button-5>", self._on_wheel, add="+")

    def _on_wheel(self, event: tk.Event) -> str:
        if getattr(event, "num", None) == 4:
            units = -3
        elif getattr(event, "num", None) == 5:
            units = 3
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return "break"
            units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        self.canvas.yview_scroll(units, "units")
        return "break"

    def _on_inner_configure(self, _event: tk.Event) -> None:
        bounds = self.canvas.bbox("all")
        if bounds:
            self.canvas.configure(scrollregion=bounds)

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)


class Avatar(tk.Canvas):
    """Круглая аватарка с инициалами."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        size: int = 46,
        bg: str | None = None,
    ) -> None:
        self.theme = theme
        self.size = size
        self._bg = bg or theme.palette.sidebar
        super().__init__(
            parent,
            width=size,
            height=size,
            bg=self._bg,
            highlightthickness=0,
            bd=0,
        )

    def show(self, title: str, seed: int | str | None = None) -> None:
        self.delete("all")
        color = avatar_color(seed if seed is not None else title)
        self.create_oval(0, 0, self.size, self.size, fill=color, outline="")
        self.create_text(
            self.size / 2,
            self.size / 2,
            text=initials(title),
            fill="#FFFFFF",
            font=self.theme.font(max(9, int(self.size * 0.33)), "bold"),
        )

    def set_background(self, color: str) -> None:
        self._bg = color
        self.configure(bg=color)


class FlatButton(tk.Button):
    """Кнопка без объёмной рамки, с подсветкой при наведении."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        text: str,
        command: Callable[[], None],
        *,
        bg: str | None = None,
        fg: str | None = None,
        hover_bg: str | None = None,
        hover_fg: str | None = None,
        font: tuple[str, int, str] | None = None,
        padx: int = 12,
        pady: int = 7,
    ) -> None:
        p = theme.palette
        self.palette = p
        self._bg = bg or p.surface
        self._fg = fg or p.text
        self._hover_bg = hover_bg or p.hover
        self._hover_fg = hover_fg or self._fg
        super().__init__(
            parent,
            text=text,
            command=command,
            bg=self._bg,
            fg=self._fg,
            activebackground=self._hover_bg,
            activeforeground=self._hover_fg,
            disabledforeground=p.muted,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=font or theme.font(10),
            padx=padx,
            pady=pady,
        )
        self.bind("<Enter>", self._on_enter, add="+")
        self.bind("<Leave>", self._on_leave, add="+")

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            self.configure(state="normal", bg=self._bg, fg=self._fg)
        else:
            self.configure(
                state="disabled",
                bg=self.palette.surface_alt,
                fg=self.palette.muted,
            )

    def _on_enter(self, _event: tk.Event) -> None:
        if self["state"] != "disabled":
            self.configure(bg=self._hover_bg, fg=self._hover_fg)

    def _on_leave(self, _event: tk.Event) -> None:
        if self["state"] != "disabled":
            self.configure(bg=self._bg, fg=self._fg)


class SearchBox(tk.Frame):
    """Поле поиска с плейсхолдером и кнопкой очистки."""

    PLACEHOLDER = "Поиск"

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        on_change: Callable[[str], None],
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        self._on_change = on_change
        self._placeholder_active = True
        super().__init__(
            parent,
            bg=self.palette.surface,
            highlightthickness=1,
            highlightbackground=self.palette.line_soft,
            highlightcolor=self.palette.accent,
        )

        self.var = tk.StringVar(value=self.PLACEHOLDER)
        self.entry = tk.Entry(
            self,
            textvariable=self.var,
            bg=self.palette.surface,
            fg=self.palette.muted,
            insertbackground=self.palette.accent,
            relief="flat",
            bd=0,
            highlightthickness=0,
            font=self.theme.font(10),
        )
        self.entry.pack(side="left", fill="x", expand=True, padx=(12, 4), pady=9)
        self.clear_button = tk.Label(
            self,
            text="×",
            bg=self.palette.surface,
            fg=self.palette.muted,
            font=self.theme.font(14),
            cursor="hand2",
        )
        self.clear_button.pack(side="right", padx=(0, 10))
        self.clear_button.bind("<Button-1>", lambda _event: self.clear())

        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.entry.bind("<Escape>", lambda _event: self.clear())
        self.var.trace_add("write", self._on_var_changed)

    def get(self) -> str:
        if self._placeholder_active:
            return ""
        return self.var.get().strip()

    def clear(self) -> None:
        self._placeholder_active = False
        self.var.set("")
        self._on_change("")
        self.entry.focus_set()

    def set_query(self, text: str) -> None:
        self._placeholder_active = False
        self.var.set(text)
        if text:
            self.entry.configure(fg=self.palette.text)
        elif self.focus_get() is not self.entry:
            self._show_placeholder()

    def _on_var_changed(self, *_args) -> None:
        if self._placeholder_active:
            return
        self._on_change(self.var.get().strip())

    def _on_focus_in(self, _event: tk.Event) -> None:
        if self._placeholder_active:
            self._placeholder_active = False
            self.var.set("")
            self.entry.configure(fg=self.palette.text)

    def _on_focus_out(self, _event: tk.Event) -> None:
        if not self.var.get().strip():
            self._show_placeholder()

    def _show_placeholder(self) -> None:
        if self._placeholder_active:
            return
        self._placeholder_active = True
        self.var.set(self.PLACEHOLDER)
        self.entry.configure(fg=self.palette.muted)


class FolderTabs(tk.Frame):
    """Горизонтальные вкладки папок."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        on_select: Callable[[str], None],
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        self._on_select = on_select
        super().__init__(parent, bg=self.palette.sidebar)

    def set_folders(
        self,
        folders: list[Folder],
        counts: dict[str, int],
        active_key: str,
    ) -> None:
        for child in self.winfo_children():
            child.destroy()

        for folder in folders:
            title = folder.title.strip() or "Папка"
            if folder.emoticon:
                title = f"{folder.emoticon} {title}"
            title = preview(title, 18)
            active = folder.key == active_key
            count = counts.get(folder.key, 0)

            tab = tk.Frame(self, bg=self.palette.sidebar, cursor="hand2")
            tab.pack(side="left", padx=(0, 16))

            label = tk.Label(
                tab,
                text=title,
                bg=self.palette.sidebar,
                fg=self.palette.accent if active else self.palette.muted,
                font=self.theme.font(10, "bold" if active else "normal"),
                cursor="hand2",
            )
            label.pack(side="left")
            count_label = tk.Label(
                tab,
                text=str(count),
                bg=self.palette.sidebar,
                fg=self.palette.accent if active else self.palette.muted,
                font=self.theme.font(8),
                cursor="hand2",
            )
            count_label.pack(side="left", padx=(4, 0))

            underline = tk.Frame(
                tab,
                bg=self.palette.accent if active else self.palette.sidebar,
                height=2,
            )
            underline.pack(fill="x", pady=(3, 0))

            for widget in (tab, label, count_label, underline):
                widget.bind(
                    "<Button-1>",
                    lambda _event, key=folder.key: self._on_select(key),
                )
                if not active:
                    self._bind_hover(widget, label, count_label)

    def _bind_hover(
        self,
        widget: tk.Misc,
        label: tk.Label,
        count_label: tk.Label,
    ) -> None:
        def enter(_event: tk.Event) -> None:
            label.configure(fg=self.palette.text_soft)
            count_label.configure(fg=self.palette.text_soft)

        def leave(_event: tk.Event) -> None:
            label.configure(fg=self.palette.muted)
            count_label.configure(fg=self.palette.muted)

        widget.bind("<Enter>", enter, add="+")
        widget.bind("<Leave>", leave, add="+")


class ChatRow(tk.Frame):
    """Строка чата: аватар, имя, превью, время и непрочитанные."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        chat: Chat,
        selected: bool,
        on_click: Callable[[int], None],
        scroll: ScrollableFrame,
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        self._normal_bg = self.palette.active if selected else self.palette.sidebar
        self._hover_bg = self.palette.active_hover if selected else self.palette.hover
        self._click = lambda: on_click(chat.id)
        self._bg_widgets: list[tk.Misc] = []

        super().__init__(parent, bg=self._normal_bg, cursor="hand2")
        self.grid_columnconfigure(1, weight=1)

        self.avatar = Avatar(
            self,
            theme,
            size=46,
            bg=self._normal_bg,
        )
        self.avatar.show(chat.title, seed=chat.id)
        self.avatar.grid(row=0, column=0, padx=(12, 10), pady=10)

        text = tk.Frame(self, bg=self._normal_bg)
        text.grid(row=0, column=1, sticky="nsew", pady=10)
        text.grid_columnconfigure(0, weight=1)
        self.title = tk.Label(
            text,
            text=preview(chat.title, 28),
            bg=self._normal_bg,
            fg=self.palette.text,
            font=self.theme.font(10, "bold"),
            anchor="w",
            cursor="hand2",
        )
        self.title.grid(row=0, column=0, sticky="ew")
        self.preview = tk.Label(
            text,
            text=preview(last_message_line(chat), 34),
            bg=self._normal_bg,
            fg=self.palette.muted,
            font=self.theme.font(9),
            anchor="w",
            cursor="hand2",
        )
        self.preview.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        meta = tk.Frame(self, bg=self._normal_bg)
        meta.grid(row=0, column=2, sticky="ne", padx=(8, 12), pady=10)
        self.time = tk.Label(
            meta,
            text=format_chat_time(chat.date),
            bg=self._normal_bg,
            fg=self.palette.muted,
            font=self.theme.font(8),
            cursor="hand2",
        )
        self.time.pack(anchor="e")

        self.badge: tk.Label | None = None
        if chat.unread > 0:
            badge_bg = self.palette.surface_alt if chat.muted else self.palette.accent
            badge_fg = self.palette.text_soft if chat.muted else self.palette.window
            self.badge = tk.Label(
                meta,
                text=unread_text(chat.unread),
                bg=badge_bg,
                fg=badge_fg,
                font=self.theme.font(8, "bold"),
                padx=6,
                pady=1,
                cursor="hand2",
            )
            self.badge.pack(anchor="e", pady=(5, 0))

        separator = tk.Frame(
            self,
            bg=self.palette.line_soft,
            height=1,
        )
        separator.grid(row=1, column=0, columnspan=3, sticky="ew")
        self._separator = separator

        self._bg_widgets = [self, text, self.title, self.preview, meta, self.time]
        for widget in self._bg_widgets:
            widget.bind("<Button-1>", lambda _event: self._click(), add="+")
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
        self.avatar.bind("<Button-1>", lambda _event: self._click(), add="+")
        self.avatar.bind("<Enter>", self._on_enter, add="+")
        self.avatar.bind("<Leave>", self._on_leave, add="+")
        if self.badge is not None:
            self.badge.bind("<Button-1>", lambda _event: self._click(), add="+")
            self.badge.bind("<Enter>", self._on_enter, add="+")
            self.badge.bind("<Leave>", self._on_leave, add="+")

        scroll.bind_wheel(self)

    def _on_enter(self, _event: tk.Event) -> None:
        self._set_bg(self._hover_bg)

    def _on_leave(self, event: tk.Event) -> None:
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self:
                return
            widget = widget.master
        self._set_bg(self._normal_bg)

    def _set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self.avatar.set_background(color)
        for widget in self._bg_widgets:
            try:
                widget.configure(bg=color)
            except tk.TclError:
                pass


class DateSeparator(tk.Frame):
    def __init__(self, parent: tk.Misc, theme: Theme, text: str) -> None:
        self.palette = theme.palette
        super().__init__(parent, bg=self.palette.window)
        label = tk.Label(
            self,
            text=text,
            bg=self.palette.surface_alt,
            fg=self.palette.muted,
            font=theme.font(8),
            padx=12,
            pady=3,
        )
        label.pack(anchor="center", pady=8)


class MessageBubble(tk.Frame):
    """Пузырь сообщения с временем и подписью отправителя."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        message: Message,
        show_sender: bool,
        wraplength: int,
        scroll: ScrollableFrame,
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        super().__init__(parent, bg=self.palette.window)
        self.wraplength = wraplength

        out = message.out
        bubble_bg = self.palette.out_bubble if out else self.palette.in_bubble
        text_color = self.palette.text if out else self.palette.text_soft
        meta_color = self.palette.text_soft if out else self.palette.muted

        bubble = tk.Frame(self, bg=bubble_bg, padx=12, pady=8)
        bubble.pack(
            side="right" if out else "left",
            padx=(70, 14) if out else (14, 70),
            pady=2,
            anchor="e" if out else "w",
        )
        bubble.grid_columnconfigure(0, weight=1)

        row = 0
        if show_sender and not out and message.sender_name:
            sender = tk.Label(
                bubble,
                text=message.sender_name,
                bg=bubble_bg,
                fg=avatar_color(message.sender_name),
                font=self.theme.font(9, "bold"),
                anchor="w",
                justify="left",
            )
            sender.grid(row=row, column=0, sticky="w", pady=(0, 3))
            row += 1

        if message.media:
            media = tk.Label(
                bubble,
                text=message.media,
                bg=bubble_bg,
                fg=self.palette.accent if not out else self.palette.white,
                font=self.theme.font(9, "bold"),
                anchor="w",
                justify="left",
            )
            media.grid(row=row, column=0, sticky="w", pady=(0, 2))
            row += 1

        text_value = message.text
        if not text_value and not message.media:
            text_value = "Сообщение"
        if text_value:
            self.text_label = tk.Label(
                bubble,
                text=text_value,
                bg=bubble_bg,
                fg=text_color,
                font=self.theme.font(10),
                anchor="w",
                justify="left",
                wraplength=wraplength,
            )
            self.text_label.grid(row=row, column=0, sticky="w")
            row += 1
        else:
            self.text_label = None

        meta = tk.Frame(bubble, bg=bubble_bg)
        meta.grid(row=row, column=0, sticky="e", pady=(3, 0))
        tk.Label(
            meta,
            text=format_message_time(message.date),
            bg=bubble_bg,
            fg=meta_color,
            font=self.theme.font(8),
        ).pack(side="right")

        scroll.bind_wheel(self)

    def set_wraplength(self, wraplength: int) -> None:
        self.wraplength = wraplength
        if self.text_label is not None:
            self.text_label.configure(wraplength=wraplength)


class EmptyState(tk.Frame):
    """Центрированная заглушка с иконкой и необязательной кнопкой."""

    def __init__(
        self,
        parent: tk.Misc,
        theme: Theme,
        title: str,
        subtitle: str,
        *,
        icon: str = "✈",
        action_text: str | None = None,
        action: Callable[[], None] | None = None,
    ) -> None:
        self.theme = theme
        self.palette = theme.palette
        super().__init__(parent, bg=self.palette.window)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        center = tk.Frame(self, bg=self.palette.window)
        center.grid(row=0, column=0)

        logo = tk.Canvas(
            center,
            width=92,
            height=92,
            bg=self.palette.window,
            highlightthickness=0,
            bd=0,
        )
        logo.pack()
        logo.create_oval(
            4,
            4,
            88,
            88,
            fill=self.palette.active,
            outline="",
        )
        logo.create_text(
            46,
            46,
            text=icon,
            fill=self.palette.white,
            font=theme.font(30, "bold"),
        )

        tk.Label(
            center,
            text=title,
            bg=self.palette.window,
            fg=self.palette.text,
            font=theme.font(16, "bold"),
        ).pack(pady=(18, 6))
        tk.Label(
            center,
            text=subtitle,
            bg=self.palette.window,
            fg=self.palette.muted,
            font=theme.font(10),
            justify="center",
            wraplength=420,
        ).pack()

        if action_text and action:
            FlatButton(
                center,
                theme,
                action_text,
                action,
                bg=self.palette.active,
                fg=self.palette.white,
                hover_bg=self.palette.active_hover,
                hover_fg=self.palette.white,
            ).pack(pady=(18, 0))
