"""Small windows: image viewer, chat picker for forwarding, file sending."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ..models import ChatItem

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"}


class ImageViewer(QDialog):
    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(path.name)
        self.setStyleSheet("QDialog { background: #0b0d11; }")
        self.pixmap = QPixmap(str(path))
        self.label = QLabel(alignment=Qt.AlignCenter)
        self.label.setMinimumSize(200, 200)
        open_btn = QPushButton("Открыть в системе", objectName="Flat")
        save_btn = QPushButton("Сохранить как…", objectName="Flat")
        close_btn = QPushButton("Закрыть", objectName="Flat")
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        save_btn.clicked.connect(self._save)
        close_btn.clicked.connect(self.accept)
        bar = QHBoxLayout()
        bar.addStretch(1)
        for b in (open_btn, save_btn, close_btn):
            bar.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addWidget(self.label, 1)
        lay.addLayout(bar)
        screen = (parent.screen() if parent else self.screen()).availableGeometry()
        size = self.pixmap.size().boundedTo(QSize(int(screen.width() * 0.85), int(screen.height() * 0.85)))
        self.resize(max(size.width(), 420), max(size.height() + 50, 320))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if not self.pixmap.isNull():
            dpr = self.devicePixelRatioF()
            pm = self.pixmap.scaled(self.label.size() * dpr, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self.label.setPixmap(pm)

    def mouseReleaseEvent(self, e):
        if self.label.geometry().contains(e.position().toPoint()):
            self.accept()

    def _save(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, "Сохранить", str(Path.home() / self.path.name))
        if target:
            Path(target).write_bytes(self.path.read_bytes())


class ChatPicker(QDialog):
    """Choose a destination chat, e.g. for forwarding."""

    def __init__(self, chats: list[ChatItem], avatars, title: str = "Переслать в…", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(380, 540)
        self.chosen: ChatItem | None = None
        self.search = QLineEdit(placeholderText="Поиск")
        self.list = QListWidget()
        self.list.setIconSize(QSize(32, 32))
        self.list.setStyleSheet("QListWidget::item { padding: 4px; } QListWidget::item:selected { background: #2e4a78; }")
        dpr = self.devicePixelRatioF()
        for chat in chats:
            it = QListWidgetItem(QIcon(avatars.pixmap(chat.peer_id, chat.title, 32, dpr, chat.kind == "self")), chat.title)
            it.setData(Qt.UserRole, chat)
            self.list.addItem(it)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._first)
        self.list.itemActivated.connect(self._pick)
        self.list.itemClicked.connect(self._pick)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            chat: ChatItem = it.data(Qt.UserRole)
            it.setHidden(bool(q) and q not in chat.title.lower() and q not in chat.username.lower())

    def _first(self) -> None:
        for i in range(self.list.count()):
            if not self.list.item(i).isHidden():
                self._pick(self.list.item(i))
                return

    def _pick(self, item: QListWidgetItem) -> None:
        self.chosen = item.data(Qt.UserRole)
        self.accept()


class SendFilesDialog(QDialog):
    """Confirm files before upload: caption and compression choice."""

    def __init__(self, paths: list[Path], caption: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Отправка файлов")
        self.resize(420, 0)
        self.paths = paths
        names = "\n".join(p.name for p in paths[:8]) + (f"\n… и ещё {len(paths) - 8}" if len(paths) > 8 else "")
        info = QLabel(names)
        info.setWordWrap(True)
        self.caption = QLineEdit(caption, placeholderText="Подпись")
        self.as_file = QCheckBox("Отправить без сжатия (как файл)")
        has_images = any(p.suffix.lower() in IMAGE_EXT for p in paths)
        self.as_file.setVisible(has_images)
        self.as_file.setChecked(not has_images)
        send = QPushButton("Отправить")
        cancel = QPushButton("Отмена", objectName="Flat")
        send.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        send.setDefault(True)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(send)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self.caption)
        lay.addWidget(self.as_file)
        lay.addLayout(buttons)
        QShortcut(QKeySequence(Qt.Key_Return), self, self.accept)
