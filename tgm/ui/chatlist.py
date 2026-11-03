"""Sidebar: search, folder tabs and the chat list."""

from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QTabBar,
    QVBoxLayout,
    QWidget,
)
from telethon.tl import types as t

from ..folders import BUILTIN, Folder
from ..models import ChatItem
from ..tasks import spawn
from . import theme
from .fmt import list_time

ROW_H = 66
AVATAR = 50
CHAT_ROLE = Qt.UserRole + 1


class ChatListModel(QAbstractListModel):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self.folder: Folder = BUILTIN[0]
        self.query = ""
        self.found: list[ChatItem] = []
        self.current_id: int | None = None
        self.rows: list[ChatItem | str] = []
        self._timer = QTimer(self, singleShot=True, interval=0, timeout=self.rebuild)

    def schedule(self) -> None:
        self._timer.start()

    def set_folder(self, folder: Folder) -> None:
        self.folder = folder
        self.rebuild()

    def set_query(self, query: str) -> None:
        self.query = query.strip().lower()
        if not self.query:
            self.found = []
        self.rebuild()

    def set_found(self, chats: list[ChatItem]) -> None:
        self.found = chats
        self.rebuild()

    def matches(self, chat: ChatItem) -> bool:
        q = self.query.lstrip("@")
        return q in chat.title.lower() or (bool(chat.username) and q in chat.username.lower())

    def rebuild(self) -> None:
        self._timer.stop()
        chats = self.service.chats.values()
        if self.query:
            shown = [c for c in chats if c.in_dialogs and self.matches(c)]
            shown.sort(key=lambda c: (c.archived, -c.sort_date))
            ids = {c.peer_id for c in shown}
            extra = [c for c in self.found if c.peer_id not in ids]
            rows: list = list(shown)
            if extra:
                rows += ["Глобальный поиск", *extra]
        else:
            rows = sorted((c for c in chats if self.folder.contains(c)), key=self.folder.rank)
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == CHAT_ROLE:
            return row
        if role == Qt.DisplayRole:
            return row if isinstance(row, str) else row.title
        return None

    def flags(self, index):
        if index.isValid() and isinstance(self.rows[index.row()], str):
            return Qt.NoItemFlags
        return super().flags(index)

    def refresh(self, peer_id: int) -> None:
        for i, row in enumerate(self.rows):
            if isinstance(row, ChatItem) and row.peer_id == peer_id:
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                return

    def first_chat(self) -> ChatItem | None:
        return next((r for r in self.rows if isinstance(r, ChatItem)), None)


class ChatDelegate(QStyledItemDelegate):
    def __init__(self, model: ChatListModel, avatars, parent=None):
        super().__init__(parent)
        self.model = model
        self.avatars = avatars
        base = QFont()
        self.title_font = QFont(base)
        self.title_font.setWeight(QFont.DemiBold)
        self.small_font = QFont(base)
        self.small_font.setPointSizeF(base.pointSizeF() * 0.86)
        self.badge_font = QFont(self.small_font)
        self.badge_font.setBold(True)

    def sizeHint(self, option, index) -> QSize:
        if isinstance(index.data(CHAT_ROLE), str):
            return QSize(0, 30)
        return QSize(0, ROW_H)

    def paint(self, p: QPainter, option, index) -> None:
        row = index.data(CHAT_ROLE)
        r = option.rect
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        if isinstance(row, str):
            p.setFont(self.small_font)
            p.setPen(QColor(theme.TEXT_DIM))
            p.drawText(r.adjusted(14, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft, row)
            p.restore()
            return
        chat: ChatItem = row
        selected = chat.peer_id == self.model.current_id
        if selected:
            p.fillRect(r, QColor(theme.SELECTED))
        elif option.state & QStyle.State_MouseOver:
            p.fillRect(r, QColor(theme.HOVER))

        dpr = p.device().devicePixelRatioF()
        ax, ay = r.left() + 10, r.top() + (ROW_H - AVATAR) // 2
        p.drawPixmap(ax, ay, self.avatars.pixmap(chat.peer_id, chat.title, AVATAR, dpr, chat.kind == "self"))
        status = getattr(chat.entity, "status", None)
        if chat.kind == "user" and isinstance(status, t.UserStatusOnline):
            p.setPen(QPen(QColor(theme.SELECTED if selected else theme.SIDEBAR), 2.5))
            p.setBrush(QColor(theme.ONLINE))
            p.drawEllipse(QRectF(ax + AVATAR - 13, ay + AVATAR - 13, 12, 12))

        left = ax + AVATAR + 12
        right = r.right() - 12
        dim = QColor("#c5d3ea" if selected else theme.TEXT_DIM)

        # top line: title … ticks time
        p.setFont(self.small_font)
        fm_small = QFontMetrics(self.small_font)
        time_text = list_time(chat.last.date) if chat.last else ""
        tw = fm_small.horizontalAdvance(time_text)
        p.setPen(dim)
        p.drawText(QRect(right - tw, r.top() + 10, tw, 20), Qt.AlignRight | Qt.AlignVCenter, time_text)
        title_right = right - tw - 6
        if chat.last and chat.last.out and not chat.last.service and chat.kind != "self":
            read = chat.last.id <= chat.read_outbox_max_id
            ticks = "✓✓" if read else "✓"
            kw = fm_small.horizontalAdvance(ticks)
            p.setPen(QColor("white" if selected else theme.ACCENT))
            p.drawText(QRect(title_right - kw, r.top() + 10, kw, 20), Qt.AlignVCenter, ticks)
            title_right -= kw + 4

        p.setFont(self.title_font)
        fm_title = QFontMetrics(self.title_font)
        suffix = " 🔇" if chat.muted else ""
        avail = title_right - left - (fm_small.horizontalAdvance(suffix) if suffix else 0)
        title = fm_title.elidedText(chat.title, Qt.ElideRight, max(avail, 10))
        p.setPen(QColor(theme.TEXT if not selected else "white"))
        p.drawText(QRect(left, r.top() + 10, avail, 20), Qt.AlignVCenter | Qt.AlignLeft, title)
        if suffix:
            p.setFont(self.small_font)
            p.setPen(dim)
            p.drawText(QRect(left + fm_title.horizontalAdvance(title), r.top() + 10, 30, 20), Qt.AlignVCenter, suffix)

        # bottom line: preview … badge
        p.setFont(self.small_font)
        badge_right = right
        badge = ""
        if chat.unread:
            badge = str(chat.unread) if chat.unread < 1000 else f"{chat.unread // 1000}K"
        elif chat.unread_mark:
            badge = " "
        bottom = QRect(left, r.top() + 34, 0, 22)
        if badge:
            p.setFont(self.badge_font)
            bw = max(22, QFontMetrics(self.badge_font).horizontalAdvance(badge) + 12)
            rect = QRectF(badge_right - bw, bottom.top(), bw, 22)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("white" if selected else (theme.BADGE_MUTED if chat.muted else theme.ACCENT)))
            p.drawRoundedRect(rect, 11, 11)
            p.setPen(QColor(theme.SELECTED if selected else "white"))
            p.drawText(rect, Qt.AlignCenter, badge)
            badge_right -= bw + 6
            if chat.mentions:
                rect = QRectF(badge_right - 22, bottom.top(), 22, 22)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("white" if selected else theme.ACCENT))
                p.drawEllipse(rect)
                p.setPen(QColor(theme.SELECTED if selected else "white"))
                p.drawText(rect, Qt.AlignCenter, "@")
                badge_right -= 28
        elif self.model.folder.is_pinned(chat) and not self.model.query:
            p.setPen(dim)
            p.drawText(QRect(badge_right - 20, bottom.top(), 20, 22), Qt.AlignCenter, "📌")
            badge_right -= 24

        p.setFont(self.small_font)
        width = badge_right - left
        x = left
        typing = chat.typing
        if typing:
            p.setPen(QColor("white" if selected else theme.ACCENT))
            p.drawText(QRect(x, bottom.top(), width, 22), Qt.AlignVCenter,
                       fm_small.elidedText(typing, Qt.ElideRight, width))
        elif chat.last:
            prefix = ""
            if chat.last.out and chat.kind not in ("self", "channel") and not chat.last.service:
                prefix = "Вы: "
            elif chat.kind == "group" and chat.last.sender_name and not chat.last.service:
                prefix = chat.last.sender_name.split()[0] + ": "
            if prefix:
                pw = fm_small.horizontalAdvance(prefix)
                p.setPen(QColor("white" if selected else theme.TEXT))
                p.drawText(QRect(x, bottom.top(), width, 22), Qt.AlignVCenter, fm_small.elidedText(prefix, Qt.ElideRight, width))
                x += pw
                width -= pw
            p.setPen(dim)
            text = chat.last.preview
            p.drawText(QRect(x, bottom.top(), max(width, 0), 22), Qt.AlignVCenter,
                       fm_small.elidedText(text, Qt.ElideRight, max(width, 0)))
        elif not chat.in_dialogs and chat.username:
            p.setPen(dim)
            p.drawText(QRect(x, bottom.top(), width, 22), Qt.AlignVCenter, "@" + chat.username)
        p.restore()


class FolderBar(QTabBar):
    folder_selected = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FolderBar")
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.ElideNone)
        self.folders: list[Folder] = []
        self.currentChanged.connect(self._changed)
        self.set_folders([])

    def set_folders(self, custom: list[Folder]) -> None:
        current = self.folders[self.currentIndex()].id if self.folders and self.currentIndex() >= 0 else None
        self.blockSignals(True)
        while self.count():
            self.removeTab(0)
        self.folders = [BUILTIN[0], *custom, BUILTIN[1]]
        for f in self.folders:
            self.addTab(f.title)
        index = next((i for i, f in enumerate(self.folders) if f.id == current), 0)
        self.setCurrentIndex(index)
        self.blockSignals(False)
        self.folder_selected.emit(self.folders[index])

    def update_counts(self, chats) -> None:
        for i, folder in enumerate(self.folders):
            n = sum(1 for c in chats if (c.unread or c.unread_mark) and not c.muted and folder.contains(c))
            self.setTabText(i, f"{folder.title}  {n}" if n else folder.title)

    def _changed(self, index: int) -> None:
        if 0 <= index < len(self.folders):
            self.folder_selected.emit(self.folders[index])


class Sidebar(QWidget):
    chat_selected = Signal(object)  # ChatItem

    def __init__(self, service, avatars, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.service = service
        self.avatars = avatars

        self.search = QLineEdit(placeholderText="Поиск")
        self.search.setClearButtonEnabled(True)
        self.banner = QLabel("Подключение…", objectName="ConnBanner", alignment=Qt.AlignCenter)
        self.banner.hide()
        self.folders = FolderBar()

        self.model = ChatListModel(service, self)
        self.view = QListView()
        self.view.setModel(self.model)
        self.view.setItemDelegate(ChatDelegate(self.model, avatars, self.view))
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(False)
        self.view.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.view.verticalScrollBar().setSingleStep(24)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.setSelectionMode(QListView.NoSelection)

        top = QHBoxLayout()
        top.setContentsMargins(10, 10, 10, 6)
        top.addWidget(self.search)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.banner)
        lay.addWidget(self.folders)
        lay.addWidget(self.view, 1)

        self._scroll = 0
        self.model.modelAboutToBeReset.connect(lambda: setattr(self, "_scroll", self.view.verticalScrollBar().value()))
        self.model.modelReset.connect(lambda: self.view.verticalScrollBar().setValue(self._scroll))
        self.model.modelReset.connect(lambda: self.folders.update_counts(self.service.chats.values()))
        self.view.clicked.connect(self._clicked)
        self.view.customContextMenuRequested.connect(self._menu)
        self.folders.folder_selected.connect(self._folder)
        self.search.textChanged.connect(self._query)
        self.search.returnPressed.connect(self._open_first)
        self._search_timer = QTimer(self, singleShot=True, interval=450, timeout=self._global_search)
        self._search_seq = 0

        avatars.ready.connect(self.model.refresh)
        service.chats_added.connect(lambda _: self.model.schedule())
        service.chat_changed.connect(lambda _: self.model.schedule())
        service.folders_changed.connect(self.folders.set_folders)
        service.status_changed.connect(self.model.refresh)
        service.state_changed.connect(self._state)

    def _state(self, state: str) -> None:
        self.banner.setVisible(state != "online")
        self.banner.setText("Подключение…" if state == "connecting" else "Нет соединения")

    def set_current(self, peer_id: int | None) -> None:
        self.model.current_id = peer_id
        self.view.viewport().update()

    def _folder(self, folder: Folder) -> None:
        self.view.verticalScrollBar().setValue(0)
        self._scroll = 0
        self.model.set_folder(folder)
        self.view.verticalScrollBar().setValue(0)

    def _clicked(self, index) -> None:
        chat = index.data(CHAT_ROLE)
        if isinstance(chat, ChatItem):
            self.chat_selected.emit(chat)

    def _open_first(self) -> None:
        chat = self.model.first_chat()
        if chat:
            self.chat_selected.emit(chat)

    def _query(self, text: str) -> None:
        self._scroll = 0
        self.model.set_query(text)
        self.view.verticalScrollBar().setValue(0)
        q = text.strip().lstrip("@")
        if len(q) >= 3:
            self._search_timer.start()
        else:
            self._search_timer.stop()
            self._search_seq += 1

    def _global_search(self) -> None:
        q = self.search.text().strip()
        self._search_seq += 1
        seq = self._search_seq

        async def run():
            found = await self.service.search_global(q.lstrip("@"))
            if seq == self._search_seq:
                self.model.set_found(found)

        spawn(run(), quiet=True)

    def _menu(self, pos) -> None:
        chat = self.view.indexAt(pos).data(CHAT_ROLE)
        if not isinstance(chat, ChatItem) or not chat.in_dialogs:
            return
        menu = QMenu(self)
        read = QAction("Отметить прочитанным", menu)
        read.setEnabled(bool(chat.unread or chat.unread_mark or chat.mentions))
        read.triggered.connect(lambda: spawn(self.service.mark_read(chat, chat.last.id if chat.last else 0)))
        menu.addAction(read)
        menu.exec(self.view.viewport().mapToGlobal(pos))
