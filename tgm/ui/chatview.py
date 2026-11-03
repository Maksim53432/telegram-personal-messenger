"""The open chat: header, message list and composer."""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlsplit

from shiboken6 import isValid
from PySide6.QtCore import QMimeData, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from telethon.tl import types

from ..models import ChatItem, MessageItem
from ..tasks import spawn
from . import theme
from .dialogs import ChatPicker, ImageViewer, SendFilesDialog
from .messages import Bubble, Context, MessageList

HEADER_AVATAR = 40


class ComposerInput(QPlainTextEdit):
    send = Signal()
    edit_last = Signal()
    cancel = Signal()
    files_pasted = Signal(list)  # [Path]

    def __init__(self, paste_dir: Path, parent=None):
        super().__init__(parent)
        self.setObjectName("ComposerInput")
        self.paste_dir = paste_dir
        self.setPlaceholderText("Сообщение")
        self.setTabChangesFocus(True)
        self.document().documentLayout().documentSizeChanged.connect(self._grow)
        self._grow()

    def _grow(self, *_):
        line = QFontMetrics(self.font()).lineSpacing()
        lines = max(1, int(self.document().size().height()))
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if lines > 8 else Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(min(lines, 8) * line + 16)

    def keyPressEvent(self, e: QKeyEvent):
        key, mods = e.key(), e.modifiers()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not (mods & (Qt.ShiftModifier | Qt.ControlModifier)):
            self.send.emit()
            return
        if key == Qt.Key_Up and not self.toPlainText():
            self.edit_last.emit()
            return
        if key == Qt.Key_Escape:
            self.cancel.emit()
            return
        super().keyPressEvent(e)

    def canInsertFromMimeData(self, source: QMimeData) -> bool:
        return source.hasImage() or source.hasUrls() or super().canInsertFromMimeData(source)

    def insertFromMimeData(self, source: QMimeData) -> None:
        files = [Path(u.toLocalFile()) for u in source.urls() if u.isLocalFile()] if source.hasUrls() else []
        if files:
            self.files_pasted.emit(files)
            return
        if source.hasImage():
            image = source.imageData()
            self.paste_dir.mkdir(parents=True, exist_ok=True)
            path = self.paste_dir / f"pasted_{int(time.time() * 1000)}.png"
            if image is not None and image.save(str(path), "PNG"):
                self.files_pasted.emit([path])
                return
        super().insertFromMimeData(source)


class ReplyBar(QFrame):
    closed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ReplyBar")
        accent = QFrame(objectName="ReplyAccent")
        accent.setFixedWidth(3)
        self.title = QLabel()
        self.title.setStyleSheet(f"color: {theme.ACCENT}; font-weight: 600;")
        self.text = QLabel()
        self.text.setStyleSheet(f"color: {theme.TEXT_DIM};")
        close = QToolButton(text="✕")
        close.clicked.connect(self.closed.emit)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(self.title)
        col.addWidget(self.text)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 6, 10, 6)
        lay.addWidget(accent)
        lay.addLayout(col, 1)
        lay.addWidget(close)
        self.hide()

    def show_for(self, title: str, text: str) -> None:
        self.title.setText(title)
        fm = QFontMetrics(self.text.font())
        self.text.setText(fm.elidedText(" ".join(text.split()), Qt.ElideRight, max(self.width() - 80, 200)))
        self.show()


class ChatView(QWidget):
    open_chat = Signal(object)  # ChatItem, from mentions and t.me links

    def __init__(self, service, avatars, toast, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatPane")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setAcceptDrops(True)
        self.service = service
        self.avatars = avatars
        self.toast = toast
        self.chat: ChatItem | None = None
        self.list: MessageList | None = None
        self.reply_to: MessageItem | None = None
        self.editing: MessageItem | None = None
        self._seq = 0
        self._status = ""

        # header
        header = QFrame(objectName="ChatHeader")
        header.setAttribute(Qt.WA_StyledBackground)
        self.h_avatar = QLabel()
        self.h_avatar.setFixedSize(HEADER_AVATAR, HEADER_AVATAR)
        self.h_title = QLabel(objectName="Title")
        self.h_status = QLabel(objectName="Muted")
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(self.h_title)
        names.addWidget(self.h_status)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(14, 8, 14, 8)
        hl.addWidget(self.h_avatar)
        hl.addSpacing(6)
        hl.addLayout(names, 1)

        self.list_holder = QStackedWidget()

        # composer
        self.reply_bar = ReplyBar()
        self.reply_bar.closed.connect(self.cancel_mode)
        composer = QFrame(objectName="Composer")
        composer.setAttribute(Qt.WA_StyledBackground)
        self.attach = QToolButton(text="📎")
        self.attach.setToolTip("Прикрепить файл")
        self.attach.setStyleSheet("font-size: 15pt;")
        self.input = ComposerInput(service.settings.cache_dir / "partial")
        self.send_btn = QToolButton(text="➤")
        self.send_btn.setToolTip("Отправить (Enter)")
        self.send_btn.setStyleSheet(f"font-size: 16pt; color: {theme.ACCENT};")
        cl = QHBoxLayout(composer)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.addWidget(self.attach, 0, Qt.AlignBottom)
        cl.addWidget(self.input, 1)
        cl.addWidget(self.send_btn, 0, Qt.AlignBottom)
        self.readonly = QLabel(alignment=Qt.AlignCenter, objectName="Muted")
        self.readonly.setMinimumHeight(48)
        self.composer_stack = QStackedWidget()
        self.composer_stack.addWidget(composer)
        self.composer_stack.addWidget(self.readonly)
        self.composer_stack.setSizePolicy(composer.sizePolicy())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(header)
        lay.addWidget(self.list_holder, 1)
        lay.addWidget(self.reply_bar)
        lay.addWidget(self.composer_stack)

        self.input.send.connect(self.submit)
        self.input.edit_last.connect(self._edit_last)
        self.input.cancel.connect(self.cancel_mode)
        self.input.files_pasted.connect(self.send_files)
        self.input.textChanged.connect(self._typed)
        self.send_btn.clicked.connect(self.submit)
        self.attach.clicked.connect(self._pick_files)

        service.message_new.connect(self._on_new)
        service.message_edited.connect(self._on_edited)
        service.messages_deleted.connect(self._on_deleted)
        service.outbox_read.connect(self._on_outbox_read)
        service.typing_changed.connect(self._on_typing)
        service.status_changed.connect(self._on_status)
        service.chat_changed.connect(self._on_chat_changed)
        avatars.ready.connect(self._on_avatar)
        self._status_timer = QTimer(self, interval=60_000, timeout=self._refresh_status)

    # --- opening

    def open(self, chat: ChatItem) -> None:
        if self.chat and chat.peer_id == self.chat.peer_id:
            return
        self._seq += 1
        seq = self._seq
        self.chat = chat
        self.cancel_mode()
        self.input.clear()

        old = self.list
        ctx = Context(self.service, self.avatars, chat)
        self.list = MessageList(ctx)
        self.list.need_older.connect(self._load_older)
        self.list.reached_bottom.connect(self.maybe_mark_read)
        self.list.jump_requested.connect(self.jump_to)
        self.list.media_clicked.connect(self._media_clicked)
        self.list.link_clicked.connect(self._link)
        self.list.context_requested.connect(self._context_menu)
        self.list.reply_requested.connect(self.start_reply)
        self.list_holder.addWidget(self.list)
        self.list_holder.setCurrentWidget(self.list)
        if old is not None:
            self.list_holder.removeWidget(old)
            old.deleteLater()

        self._paint_header()
        self._status = ""
        self._refresh_status()
        self._status_timer.start()
        if chat.can_write:
            self.composer_stack.setCurrentIndex(0)
            self.input.setFocus()
        else:
            self.readonly.setText("Канал — только чтение" if chat.kind == "channel" else "Писать в этот чат нельзя")
            self.composer_stack.setCurrentIndex(1)
        self.composer_stack.setFixedHeight(self.composer_stack.currentWidget().sizeHint().height())

        unread = chat.unread
        limit = max(50, unread + 20) if unread <= 80 else 50

        async def load():
            items = await self.service.history(chat, limit=min(limit, 100))
            if seq != self._seq:
                return
            first_unread = None
            if 0 < unread <= 80:
                first_unread = next((i.id for i in items if not i.out and i.id > chat.read_inbox_max_id), None)
            self.list.set_messages(items, first_unread)
            QTimer.singleShot(50, self.maybe_mark_read)

        spawn(load())

    def _paint_header(self) -> None:
        chat = self.chat
        self.h_title.setText(chat.title)
        self.h_avatar.setPixmap(self.avatars.pixmap(chat.peer_id, chat.title, HEADER_AVATAR,
                                                    self.devicePixelRatioF(), chat.kind == "self"))

    def _refresh_status(self) -> None:
        chat = self.chat
        if chat is None:
            return
        seq = self._seq

        async def run():
            text = await self.service.describe(chat)
            if seq == self._seq:
                self._status = text
                self._show_status()

        spawn(run(), quiet=True)

    def _show_status(self) -> None:
        typing = self.service.typing_text(self.chat.peer_id) if self.chat else ""
        if typing:
            self.h_status.setStyleSheet(f"color: {theme.ACCENT};")
            self.h_status.setText(typing)
        else:
            online = self._status == "в сети"
            self.h_status.setStyleSheet(f"color: {theme.LINK if online else theme.TEXT_DIM};")
            self.h_status.setText(self._status)
        self.h_status.setVisible(bool(self.h_status.text()))

    def _on_typing(self, chat_id) -> None:
        if self.chat and chat_id == self.chat.peer_id:
            self._show_status()

    def _on_status(self, user_id) -> None:
        if self.chat and user_id == self.chat.peer_id:
            self._refresh_status()

    def _on_avatar(self, peer_id) -> None:
        if self.chat and peer_id == self.chat.peer_id:
            self._paint_header()

    def _on_chat_changed(self, chat) -> None:
        if self.chat and chat.peer_id == self.chat.peer_id and chat.title != self.h_title.text():
            self._paint_header()

    # --- history

    def _load_older(self) -> None:
        lst, chat = self.list, self.chat
        if lst is None or lst.loading_older or lst.at_start:
            return
        lst.loading_older = True
        seq = self._seq

        async def run():
            try:
                items = await self.service.history(chat, offset_id=lst.oldest_id(), limit=50)
                if seq != self._seq:
                    return
                if not items:
                    lst.at_start = True
                lst.prepend(items)
            finally:
                lst.loading_older = False

        spawn(run())

    def jump_to(self, msg_id: int) -> None:
        lst, chat, seq = self.list, self.chat, self._seq
        if lst.show_message(msg_id):
            return

        async def run():
            for _ in range(10):
                if lst.at_start or seq != self._seq:
                    break
                lst.loading_older = True
                try:
                    items = await self.service.history(chat, offset_id=lst.oldest_id(), limit=100)
                finally:
                    lst.loading_older = False
                if seq != self._seq:
                    return
                if not items:
                    lst.at_start = True
                lst.prepend(items)
                if msg_id in lst.rows:
                    QTimer.singleShot(150, lambda: lst.show_message(msg_id))
                    return
            self.toast("Сообщение не найдено")

        spawn(run())

    def maybe_mark_read(self) -> None:
        chat, lst = self.chat, self.list
        if not chat or not lst or not self.window().isActiveWindow() or not lst.stick_bottom:
            return
        newest = lst.newest_id()
        if newest and (newest > chat.read_inbox_max_id or chat.unread or chat.unread_mark):
            spawn(self.service.mark_read(chat, newest), quiet=True)

    # --- live updates

    def _on_new(self, item: MessageItem) -> None:
        if self.chat and self.list and item.chat_id == self.chat.peer_id:
            self.list.add(item)
            if not item.out:
                QTimer.singleShot(50, self.maybe_mark_read)

    def _on_edited(self, item: MessageItem) -> None:
        if self.chat and self.list and item.chat_id == self.chat.peer_id and item.id in self.list.rows:
            self.list.add(item)

    def _on_deleted(self, chat_id, ids: list) -> None:
        if not self.chat or not self.list:
            return
        # Without a chat id the ids belong to the shared box of private chats and small groups.
        in_channel = isinstance(self.chat.entity, types.Channel)
        if (chat_id is None and in_channel) or (chat_id is not None and chat_id != self.chat.peer_id):
            return
        self.list.remove(ids)

    def _on_outbox_read(self, chat_id, _max_id) -> None:
        if self.chat and self.list and chat_id == self.chat.peer_id:
            self.list.refresh_read()

    # --- composing

    def _typed(self) -> None:
        if self.chat and self.input.toPlainText() and not self.editing and self.chat.kind != "self":
            spawn(self.service.send_typing(self.chat), quiet=True)

    def submit(self) -> None:
        chat = self.chat
        text = self.input.toPlainText().strip()
        if not chat or not text:
            return
        editing, reply = self.editing, self.reply_to
        self.input.clear()
        self.cancel_mode()

        def restore(error: str) -> None:
            self.toast(error)
            if not self.input.toPlainText():
                self.input.setPlainText(text)

        if editing:
            spawn(self.service.edit(chat, editing.id, text), on_error=restore)
        else:
            self.list.stick_bottom = True
            spawn(self.service.send_text(chat, text, reply.id if reply else None), on_error=restore)

    def start_reply(self, item: MessageItem) -> None:
        if not self.chat or not self.chat.can_write or item.service:
            return
        self.editing = None
        self.reply_to = item
        self.reply_bar.show_for(f"Ответ {item.sender_name}" if item.sender_name else "Ответ", item.preview)
        self.input.setFocus()

    def start_edit(self, item: MessageItem) -> None:
        self.reply_to = None
        self.editing = item
        self.reply_bar.show_for("Редактирование", item.text)
        self.input.setPlainText(item.text)
        self.input.moveCursor(self.input.textCursor().MoveOperation.End)
        self.input.setFocus()

    def cancel_mode(self) -> None:
        if self.editing:
            self.input.clear()
        self.reply_to = None
        self.editing = None
        self.reply_bar.hide()

    def _edit_last(self) -> None:
        if self.list:
            item = self.list.last_own_text()
            if item:
                self.start_edit(item)

    # --- files

    def _pick_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Выберите файлы", str(Path.home()))
        if files:
            self.send_files([Path(f) for f in files])

    def send_files(self, paths: list[Path]) -> None:
        chat = self.chat
        if not chat or not chat.can_write:
            return
        paths = [p for p in paths if p.is_file()]
        if not paths:
            return
        dialog = SendFilesDialog(paths, self.input.toPlainText().strip(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        caption = dialog.caption.text().strip()
        as_file = dialog.as_file.isChecked()
        if caption and caption == self.input.toPlainText().strip():
            self.input.clear()
        reply = self.reply_to.id if self.reply_to else None
        self.cancel_mode()

        async def run():
            for n, path in enumerate(paths):
                label = path.name if len(paths) == 1 else f"{path.name} ({n + 1}/{len(paths)})"

                def progress(sent, total, label=label):
                    if total:
                        self.toast(f"Отправка {label}: {sent * 100 // total}%", 2500)

                await self.service.send_file(chat, str(path), caption if n == 0 else "", reply if n == 0 else None,
                                             as_document=as_file, progress=progress)
            self.toast("Отправлено", 1500)

        self.list.stick_bottom = True
        spawn(run())

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and self.chat and self.chat.can_write:
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            e.acceptProposedAction()
            self.send_files(files)

    # --- media & links

    def _media_clicked(self, item: MessageItem, bubble: Bubble) -> None:
        kind = item.media.kind
        row = bubble.file_row

        def progress(got, total):
            if not total:
                return
            pct = f"{got * 100 // total}%"
            if row is not None and isValid(row):
                row.set_status(pct)
            else:
                self.toast(f"Загрузка: {pct}", 2000)

        async def run():
            path = await self.service.download(item, progress)
            if row is not None and isValid(row):
                row.set_status("")
            if kind == "photo":
                ImageViewer(path, self.window()).exec()
            else:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

        spawn(run())

    def _link(self, url: str) -> None:
        if url.startswith("tgm-user:"):
            self._open_username(url.removeprefix("tgm-user:"))
            return
        if url.startswith("tgm-peer:"):
            spawn(self._open_peer(int(url.removeprefix("tgm-peer:"))))
            return
        parts = urlsplit(url)
        if parts.hostname in ("t.me", "telegram.me"):
            segs = [s for s in parts.path.split("/") if s]
            if len(segs) in (1, 2) and segs[0].replace("_", "").isalnum() and segs[0] not in ("joinchat", "addstickers", "proxy", "share"):
                self._open_username(segs[0])
                return
        QDesktopServices.openUrl(QUrl(url))

    def _open_username(self, username: str) -> None:
        async def run():
            self.open_chat.emit(await self.service.resolve_username(username))

        spawn(run())

    async def _open_peer(self, peer_id: int) -> None:
        self.open_chat.emit(await self.service.resolve_peer(peer_id))

    # --- context menu

    def _context_menu(self, item: MessageItem, bubble: Bubble, pos: QPoint) -> None:
        chat = self.chat
        menu = QMenu(self)

        def add(text: str, slot, enabled: bool = True) -> None:
            act = QAction(text, menu)
            act.setEnabled(enabled)
            act.triggered.connect(slot)
            menu.addAction(act)

        if not item.service:
            if chat.can_write:
                add("Ответить", lambda: self.start_reply(item))
            selected = bubble.text_label.selectedText() if bubble.text_label else ""
            if selected:
                add("Копировать выделенное", lambda: QGuiApplication.clipboard().setText(selected))
            if item.text:
                add("Копировать текст", lambda: QGuiApplication.clipboard().setText(item.text))
            if chat.username:
                link = f"https://t.me/{chat.username}/{item.id}"
                add("Копировать ссылку", lambda: QGuiApplication.clipboard().setText(link))
            add("Переслать…", lambda: self._forward(item))
            if item.out and item.text and not item.forward:
                add("Изменить", lambda: self.start_edit(item))
            if item.media and item.media.kind not in ("webpage", "geo", "contact", "poll", "other"):
                menu.addSeparator()
                add("Открыть", lambda: self._media_clicked(item, bubble))
                add("Сохранить как…", lambda: self._save_as(item))
        menu.addSeparator()
        add("Удалить…", lambda: self._delete(item))
        menu.exec(pos)

    def _forward(self, item: MessageItem) -> None:
        chats = sorted((c for c in self.service.chats.values() if c.in_dialogs and c.can_write),
                       key=lambda c: (c.kind != "self", -c.sort_date))
        picker = ChatPicker(chats, self.avatars, parent=self)
        if picker.exec() == QDialog.Accepted and picker.chosen:
            target, source = picker.chosen, self.chat

            async def run():
                await self.service.forward(source, [item.id], target)
                self.toast(f"Переслано в «{target.title}»", 2000)

            spawn(run())

    def _save_as(self, item: MessageItem) -> None:
        async def run():
            path = await self.service.download(item)
            target, _ = QFileDialog.getSaveFileName(self, "Сохранить", str(Path.home() / path.name.split("_", 2)[-1]))
            if target:
                Path(target).write_bytes(path.read_bytes())

        spawn(run())

    def _delete(self, item: MessageItem) -> None:
        chat = self.chat
        box = QMessageBox(self)
        box.setWindowTitle("Удалить сообщение")
        box.setText("Удалить это сообщение?")
        revoke = QCheckBox(f"Удалить также у {chat.title}" if chat.kind in ("user", "bot") else "Удалить у всех")
        can_revoke = chat.kind in ("user", "bot") or item.out or chat.kind == "channel"
        revoke.setVisible(can_revoke and chat.kind != "self")
        revoke.setChecked(can_revoke)
        box.setCheckBox(revoke)
        confirm = box.addButton("Удалить", QMessageBox.AcceptRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is confirm:
            spawn(self.service.delete(chat, [item.id], revoke.isChecked() or chat.kind == "channel"))
