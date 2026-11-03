"""Top-level window: connecting screen, login, or sidebar + chat."""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime, timezone

from PySide6.QtCore import QEvent, QProcess, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from ..config import Settings
from ..service import TelegramService
from ..tasks import set_error_sink, spawn
from .avatars import AvatarStore
from .chatlist import Sidebar
from .chatview import ChatView
from .login import LoginPage


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent, objectName="Toast")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        self._timer = QTimer(self, singleShot=True, timeout=self.hide)

    def __call__(self, text: str, ms: int = 4000) -> None:
        self.setText(text)
        self.setMaximumWidth(min(520, self.parentWidget().width() - 40))
        self.adjustSize()
        p = self.parentWidget()
        self.move((p.width() - self.width()) // 2, p.height() - self.height() - 90)
        self.raise_()
        self.show()
        self._timer.start(ms)


def _centered(text: str) -> QWidget:
    page = QWidget(objectName="EmptyState")
    page.setAttribute(Qt.WA_StyledBackground)
    label = QLabel(text, alignment=Qt.AlignCenter, objectName="Muted")
    lay = QVBoxLayout(page)
    lay.addWidget(label)
    page.label = label
    return page


class MainWindow(QMainWindow):
    finished = Signal()  # emitted once the client has disconnected after close

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.setWindowTitle("Telegram")
        self.resize(1200, 800)
        self.prefs = QSettings(str(settings.data_dir / "ui.ini"), QSettings.IniFormat)

        self.service = TelegramService(settings, self)
        self.avatars = AvatarStore(self.service, self)
        self.toast = Toast(self)
        set_error_sink(self.toast)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.connecting = _centered("Подключение к Telegram…")
        self.login = LoginPage(self.service)

        self.sidebar = Sidebar(self.service, self.avatars)
        self.chat_view = ChatView(self.service, self.avatars, self.toast)
        self.empty = _centered("Выберите чат")
        self.right = QStackedWidget()
        self.right.addWidget(self.empty)
        self.right.addWidget(self.chat_view)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.right)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        self.sidebar.setMinimumWidth(260)
        self.splitter.setSizes([360, 840])

        for page in (self.connecting, self.login, self.splitter):
            self.stack.addWidget(page)

        self.sidebar.chat_selected.connect(self.open_chat)
        self.chat_view.open_chat.connect(self.open_chat)
        self.service.auth_required.connect(lambda: self.stack.setCurrentWidget(self.login))
        self.service.authorized.connect(lambda _: self.stack.setCurrentWidget(self.splitter))
        self.service.chats_loaded.connect(lambda: setattr(self, "_loaded", True))
        self.service.message_new.connect(self._notify)
        self.service.chat_changed.connect(lambda _: self._title_timer.start())
        self.service.chats_added.connect(lambda _: self._title_timer.start())
        self.service.typing_changed.connect(self._typing)

        QShortcut(QKeySequence("Ctrl+F"), self, lambda: self.sidebar.search.setFocus())
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        QShortcut(QKeySequence(Qt.Key_Escape), self.sidebar, lambda: self.sidebar.search.clear())

        self._title_timer = QTimer(self, singleShot=True, interval=200, timeout=self._update_title)
        self._loaded = False
        self._closing = False
        self._notify_send = shutil.which("notify-send")
        self._restore()

    async def start(self) -> None:
        try:
            await self.service.start()
        except Exception as exc:
            self.connecting.label.setText(f"Не удалось подключиться: {exc}")
            raise

    def open_chat(self, chat) -> None:
        self.sidebar.set_current(chat.peer_id)
        self.right.setCurrentWidget(self.chat_view)
        self.chat_view.open(chat)

    def _typing(self, chat_id) -> None:
        chat = self.service.chats.get(chat_id)
        if chat is not None:
            chat.typing = self.service.typing_text(chat_id)
            self.sidebar.model.refresh(chat_id)

    def _update_title(self) -> None:
        unread = sum(1 for c in self.service.chats.values()
                     if c.in_dialogs and (c.unread or c.unread_mark) and not c.muted and not c.archived)
        self.setWindowTitle(f"Telegram ({unread})" if unread else "Telegram")

    def _notify(self, item) -> None:
        if not self.settings.notify or not self._notify_send or not self._loaded:
            return
        if item.out or item.service:
            return
        if (datetime.now(timezone.utc) - item.date).total_seconds() > 60:
            return  # catching up after being offline
        chat = self.service.chats.get(item.chat_id)
        if chat is None or chat.muted or chat.kind == "self":
            return
        if self.isActiveWindow() and self.chat_view.chat and self.chat_view.chat.peer_id == chat.peer_id:
            return
        title = chat.title if chat.kind in ("user", "bot") else f"{item.sender_name} → {chat.title}"
        body = item.preview[:200]
        QProcess.startDetached(self._notify_send, ["-a", "Telegram", "-i", "telegram", title, body])

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.ActivationChange and self.isActiveWindow():
            self.chat_view.maybe_mark_read()

    def _restore(self) -> None:
        geometry = self.prefs.value("geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        splitter = self.prefs.value("splitter")
        if splitter is not None:
            self.splitter.restoreState(splitter)

    def closeEvent(self, e):
        if self._closing:
            e.accept()
            return
        e.ignore()
        self._closing = True
        self.prefs.setValue("geometry", self.saveGeometry())
        self.prefs.setValue("splitter", self.splitter.saveState())
        self.prefs.sync()
        self.hide()

        async def shutdown():
            try:
                await asyncio.wait_for(self.service.stop(), 5)
            finally:
                self.finished.emit()

        spawn(shutdown(), quiet=True)
