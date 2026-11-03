"""Message history: bubbles, day separators and scrolling."""

from __future__ import annotations

import math
import re
from datetime import date

from shiboken6 import isValid
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..models import ChatItem, MessageItem, human_duration, human_size, media_label, peer_color
from ..tasks import spawn
from . import theme
from .fmt import clock, day_title, local

GROUP_AVATAR = 34
MEDIA_MAX_W = 420
MEDIA_MAX_H = 440
STICKER = 180
ROUND = 220
_LONG_WORD = re.compile(r"[^\s<>&]{48,}")
_TAGS = re.compile(r"<[^>]+>")


def _break_long_words(html: str) -> str:
    """QLabel cannot wrap inside a word; give very long tokens (URLs) break opportunities."""
    return _LONG_WORD.sub(lambda m: "​".join(m.group(0)[i:i + 24] for i in range(0, len(m.group(0)), 24)), html)


class Context:
    """What bubbles need to know about the open chat and the outside world."""

    def __init__(self, service, avatars, chat: ChatItem):
        self.service = service
        self.avatars = avatars
        self.chat = chat
        self.max_width = 520
        self.list: MessageList | None = None

    @property
    def show_names(self) -> bool:
        return self.chat.kind == "group"


# --- small parts -----------------------------------------------------------


class RichLabel(QLabel):
    def __init__(self, html: str, parent=None):
        super().__init__(parent)
        self._html = _break_long_words(html)
        self.setTextFormat(Qt.RichText)
        self.setText(self._html)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setOpenExternalLinks(False)
        self._single_line = True

    def fit(self, max_w: int) -> None:
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(0)
        doc.setHtml(self._html)
        ideal = math.ceil(doc.idealWidth()) + 2
        width = max(min(ideal, max_w), 8)
        doc.setTextWidth(width)
        line = QFontMetrics(self.font()).lineSpacing()
        self._single_line = doc.size().height() < line * 1.6
        self.setFixedWidth(width)

    @property
    def single_line(self) -> bool:
        return self._single_line


class ReplyQuote(QWidget):
    clicked = Signal()

    def __init__(self, sender: str, text: str, color: str, parent=None):
        super().__init__(parent)
        self.sender = sender or "Сообщение"
        self.text = " ".join(text.split())
        self.color = QColor(color)
        self.setCursor(Qt.PointingHandCursor)
        self.bold = QFont(self.font())
        self.bold.setWeight(QFont.DemiBold)
        self.setFixedHeight(QFontMetrics(self.font()).height() * 2 + 10)
        self._max = 300

    def fit(self, max_w: int) -> None:
        natural = max(QFontMetrics(self.bold).horizontalAdvance(self.sender),
                      QFontMetrics(self.font()).horizontalAdvance(self.text)) + 18
        self.setFixedWidth(min(natural, max_w))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(self.color)
        bg.setAlpha(36)
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 6, 6)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 0, 3, self.height()), 1.5, 1.5)
        w = self.width() - 14
        h = QFontMetrics(self.font()).height()
        p.setFont(self.bold)
        p.setPen(self.color)
        p.drawText(10, 4, w, h, Qt.AlignLeft | Qt.AlignVCenter, QFontMetrics(self.bold).elidedText(self.sender, Qt.ElideRight, w))
        p.setFont(self.font())
        p.setPen(QColor(theme.TEXT))
        p.drawText(10, 4 + h + 2, w, h, Qt.AlignLeft | Qt.AlignVCenter, QFontMetrics(self.font()).elidedText(self.text, Qt.ElideRight, w))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class MediaView(QWidget):
    """Photo / video / sticker preview with a reserved size, so loading never shifts the layout."""

    clicked = Signal()

    def __init__(self, ctx: Context, item: MessageItem, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.media = item.media
        self.image: QImage | None = None
        self.loaded = False
        if self.media.stripped:
            img = QImage.fromData(self.media.stripped)
            if not img.isNull():
                self.image = img
        self.bare = self.media.kind in ("sticker", "round")
        self.setCursor(Qt.ArrowCursor if self.media.kind == "sticker" else Qt.PointingHandCursor)
        self.fit(ctx.max_width)

    def target_size(self, max_w: int) -> QSize:
        m = self.media
        if m.kind == "sticker":
            if m.width and m.height:
                k = STICKER / max(m.width, m.height)
                return QSize(max(int(m.width * k), 60), max(int(m.height * k), 60))
            return QSize(STICKER, STICKER)
        if m.kind == "round":
            return QSize(ROUND, ROUND)
        w, h = m.width or 320, m.height or 240
        max_w = min(max_w, MEDIA_MAX_W)
        scale = min(max_w / w, MEDIA_MAX_H / h, 1.0 if max(w, h) > 160 else 2.0)
        return QSize(max(int(w * scale), 120), max(int(h * scale), 80))

    def fit(self, max_w: int) -> None:
        self.setFixedSize(self.target_size(max_w))

    def load(self) -> None:
        if self.loaded:
            return
        self.loaded = True

        async def run():
            path = await self.ctx.service.thumbnail(self.item)
            if path and isValid(self):
                img = QImage(str(path))
                if not img.isNull():
                    self.image = img
                    self.update()

        spawn(run(), quiet=True)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        if self.media.kind == "round":
            path.addEllipse(r)
        else:
            path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        if self.image is not None:
            if self.media.kind == "sticker":
                img = self.image.scaled(self.size() * self.devicePixelRatioF(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                img.setDevicePixelRatio(self.devicePixelRatioF())
                sz = img.deviceIndependentSize()
                p.drawImage(QRectF((r.width() - sz.width()) / 2, (r.height() - sz.height()) / 2, sz.width(), sz.height()), img)
            else:
                src = self.image.rect()
                # cover: crop the image to the widget's aspect ratio
                ratio = r.width() / r.height()
                sw, sh = src.width(), src.height()
                if sw / max(sh, 1) > ratio:
                    cw = sh * ratio
                    srect = QRectF((sw - cw) / 2, 0, cw, sh)
                else:
                    ch = sw / ratio
                    srect = QRectF(0, (sh - ch) / 2, sw, ch)
                p.drawImage(r, self.image, srect)
        elif self.media.kind == "sticker":
            p.setPen(QColor(theme.TEXT))
            f = QFont(self.font())
            f.setPixelSize(72)
            p.setFont(f)
            p.drawText(r, Qt.AlignCenter, self.media.emoji or "🖼")
        else:
            p.fillRect(r, QColor("#2a303b"))
        if self.media.spoiler and self.media.kind == "photo":
            p.fillRect(r, QColor(20, 24, 30, 170))
        p.setClipping(False)
        if self.media.kind in ("video", "gif", "round"):
            self._overlay(p, r)

    def _overlay(self, p: QPainter, r: QRectF) -> None:
        d = 46
        c = QRectF(r.center().x() - d / 2, r.center().y() - d / 2, d, d)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 140))
        p.drawEllipse(c)
        p.setBrush(QColor("white"))
        tri = [QPoint(int(c.left() + 18), int(c.top() + 13)), QPoint(int(c.left() + 18), int(c.bottom() - 13)),
               QPoint(int(c.right() - 13), int(c.center().y()))]
        p.drawPolygon(tri)
        label = "GIF" if self.media.kind == "gif" else human_duration(self.media.duration) if self.media.duration else ""
        if label:
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() * 0.85)
            p.setFont(f)
            w = QFontMetrics(f).horizontalAdvance(label) + 12
            box = QRectF(8, 8, w, 20)
            p.setBrush(QColor(0, 0, 0, 140))
            p.drawRoundedRect(box, 10, 10)
            p.setPen(QColor("white"))
            p.drawText(box, Qt.AlignCenter, label)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.media.kind != "sticker":
            self.clicked.emit()


class FileRow(QWidget):
    """Documents, audio and voice: an icon plus name and size; click downloads and opens."""

    clicked = Signal()

    def __init__(self, item: MessageItem, parent=None):
        super().__init__(parent)
        m = item.media
        self.media = m
        icons = {"voice": "🎤", "audio": "🎵", "document": "📄", "video": "🎬"}
        self.icon = icons.get(m.kind, "📄")
        if m.kind == "voice":
            self.title, self.sub = "Голосовое сообщение", human_duration(m.duration)
        elif m.kind == "audio":
            self.title = m.title or m.file_name or "Аудио"
            self.sub = " · ".join(x for x in (m.subtitle, human_duration(m.duration) if m.duration else "") if x)
        else:
            self.title, self.sub = m.file_name or media_label(m), human_size(m.size) if m.size else ""
        self.status = ""
        self.setCursor(Qt.PointingHandCursor)
        self.bold = QFont(self.font())
        self.bold.setWeight(QFont.DemiBold)
        self.small = QFont(self.font())
        self.small.setPointSizeF(self.font().pointSizeF() * 0.88)
        self.setFixedHeight(48)

    def fit(self, max_w: int) -> None:
        natural = 58 + max(QFontMetrics(self.bold).horizontalAdvance(self.title),
                           QFontMetrics(self.small).horizontalAdvance(self.sub + "  100%")) + 6
        self.setFixedWidth(min(max(natural, 180), max_w))

    def set_status(self, text: str) -> None:
        self.status = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(QRectF(0, 2, 44, 44))
        f = QFont(self.font())
        f.setPixelSize(20)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(0, 2, 44, 44), Qt.AlignCenter, self.icon)
        w = self.width() - 56
        p.setFont(self.bold)
        p.setPen(QColor(theme.TEXT))
        p.drawText(54, 4, w, 20, Qt.AlignVCenter, QFontMetrics(self.bold).elidedText(self.title, Qt.ElideMiddle, w))
        p.setFont(self.small)
        p.setPen(QColor(theme.TEXT_DIM))
        sub = f"{self.sub}  {self.status}".strip()
        p.drawText(54, 25, w, 18, Qt.AlignVCenter, QFontMetrics(self.small).elidedText(sub, Qt.ElideRight, w))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit()


class InfoBox(QLabel):
    """Link previews, polls, contacts, locations: accent bar + title + text."""

    def __init__(self, title: str, body: str, link: str = "", parent=None):
        super().__init__(parent)
        from html import escape

        parts = []
        if title:
            parts.append(f'<b style="color:{theme.LINK}">{escape(title)}</b>')
        if body:
            short = body if len(body) < 300 else body[:297] + "…"
            parts.append(escape(short).replace("\n", "<br>"))
        if link:
            parts.append(f'<a href="{escape(link, quote=True)}">Открыть</a>')
        self._html = "<br>".join(parts)
        self.setTextFormat(Qt.RichText)
        self.setText(self._html)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.setStyleSheet(f"QLabel {{ border-left: 3px solid {theme.ACCENT}; padding-left: 8px; }}")

    def fit(self, max_w: int) -> None:
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(0)
        doc.setHtml(self._html)
        self.setFixedWidth(max(min(math.ceil(doc.idealWidth()) + 16, max_w), 60))


# --- bubbles ---------------------------------------------------------------


class Bubble(QFrame):
    def __init__(self, ctx: Context, item: MessageItem, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.flash = 0.0
        self.media_view: MediaView | None = None
        self.file_row: FileRow | None = None
        self.text_label: RichLabel | None = None
        self.parts: list[QWidget] = []
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self._build()

    @property
    def bare(self) -> bool:
        return bool(self.media_view and self.media_view.bare and not self.item.text and not self.item.reply)

    def _small(self) -> QFont:
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 0.82)
        return f

    def _build(self) -> None:
        item, ctx = self.item, self.ctx
        lay = QVBoxLayout(self)
        lay.setSpacing(4)
        lay.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        self.name = QLabel(item.sender_name or "")
        self.name.setStyleSheet(f"color: {peer_color(item.sender_id)}; font-weight: 600;")
        lay.addWidget(self.name)
        self.name.setVisible(ctx.show_names and not item.out)

        if item.forward:
            fwd = QLabel(f"Переслано от <b>{_esc(item.forward)}</b>")
            fwd.setStyleSheet(f"color: {theme.LINK};")
            fwd.setFont(self._small())
            lay.addWidget(fwd)
        if item.via_bot:
            via = QLabel(f"через @{_esc(item.via_bot)}")
            via.setStyleSheet(f"color: {theme.TEXT_DIM};")
            via.setFont(self._small())
            lay.addWidget(via)
        if item.reply:
            color = peer_color(item.reply.sender_id)
            quote = ReplyQuote(item.reply.sender, item.reply.text or "…", theme.LINK if item.out else color)
            quote.clicked.connect(lambda: ctx.list and ctx.list.jump_requested.emit(item.reply.msg_id))
            self.parts.append(quote)
            lay.addWidget(quote)

        m = item.media
        if m:
            if m.kind in ("photo", "video", "gif", "round", "sticker"):
                self.media_view = MediaView(ctx, item)
                self.media_view.clicked.connect(lambda: ctx.list and ctx.list.media_clicked.emit(item, self))
                lay.addWidget(self.media_view)
            elif m.kind in ("voice", "audio", "document"):
                self.file_row = FileRow(item)
                self.file_row.clicked.connect(lambda: ctx.list and ctx.list.media_clicked.emit(item, self))
                self.parts.append(self.file_row)
                lay.addWidget(self.file_row)

        self.text_row = QHBoxLayout()
        self.text_row.setSpacing(10)
        if item.text:
            self.text_label = RichLabel(item.html)
            self.text_label.linkActivated.connect(lambda url: ctx.list and ctx.list.link_clicked.emit(url))
            self.text_row.addWidget(self.text_label, 0, Qt.AlignLeft)
        self.inline_meta = QLabel()
        self.inline_meta.setFont(self._small())
        self.text_row.addWidget(self.inline_meta, 0, Qt.AlignRight | Qt.AlignBottom)
        lay.addLayout(self.text_row)

        if m and m.kind in ("webpage", "geo", "contact", "poll", "other"):
            box = InfoBox(m.title, m.subtitle, m.url if m.kind == "geo" else "")
            box.linkActivated.connect(lambda url: ctx.list and ctx.list.link_clicked.emit(url))
            self.parts.append(box)
            lay.addWidget(box)

        self.meta_row = QHBoxLayout()
        self.meta_row.setSpacing(8)
        self.reactions = QLabel(item.reactions)
        self.reactions.setVisible(bool(item.reactions))
        self.meta_row.addWidget(self.reactions)
        self.meta_row.addStretch(1)
        self.meta = QLabel()
        self.meta.setFont(self._small())
        self.meta_row.addWidget(self.meta)
        lay.addLayout(self.meta_row)

        if self.bare:
            lay.setContentsMargins(0, 0, 0, 0)
            self.meta.setStyleSheet("background: rgba(0,0,0,0.45); border-radius: 8px; padding: 1px 6px; color: white;")
        else:
            lay.setContentsMargins(11, 7, 11, 6)
        self.refresh_meta()

    def meta_text(self) -> str:
        item, chat = self.item, self.ctx.chat
        parts = []
        if item.edited:
            parts.append("изм.")
        if item.views is not None and chat.kind == "channel":
            parts.append(f"👁 {_compact(item.views)}")
        if item.post_author:
            parts.append(_esc(item.post_author))
        parts.append(clock(item.date))
        text = "  ".join(parts)
        if item.out and chat.kind != "self":
            read = item.id <= chat.read_outbox_max_id
            text += f'  <span style="color:{theme.LINK if read else theme.TEXT_DIM}">{"✓✓" if read else "✓"}</span>'
        return text

    def refresh_meta(self) -> None:
        color = "#c9d6ec" if self.item.out else theme.TEXT_DIM
        html = f'<span style="color:{color}">{self.meta_text()}</span>'
        self.meta.setText(html)
        self.inline_meta.setText(html)
        self.fit(self.ctx.max_width)

    def fit(self, max_w: int) -> None:
        inner = max_w - (0 if self.bare else 22)
        for part in self.parts:
            part.fit(inner)
        if self.media_view:
            self.media_view.fit(inner)
        inline = False
        if self.text_label:
            self.text_label.fit(inner)
            meta_w = QFontMetrics(self._small()).horizontalAdvance(_TAGS.sub("", self.inline_meta.text())) + 14
            # Inline the time on single-line text when it fits, like most messengers do.
            inline = self.text_label.single_line and self.text_label.width() + meta_w <= inner \
                and not self.media_view and not self.item.reactions and not self.file_row
        self.inline_meta.setVisible(inline)
        self.meta.setVisible(not inline)

    def set_run_start(self, start: bool) -> None:
        if self.ctx.show_names and not self.item.out:
            self.name.setVisible(start)

    def start_flash(self) -> None:
        self.flash = 1.0
        timer = QTimer(self, interval=40)

        def step():
            self.flash = max(0.0, self.flash - 0.04)
            self.update()
            if self.flash <= 0:
                timer.stop()
                timer.deleteLater()

        timer.timeout.connect(step)
        timer.start()

    def paintEvent(self, _):
        if self.bare and not self.flash:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        color = QColor(theme.BUBBLE_OUT if self.item.out else theme.BUBBLE_IN)
        if self.bare:
            color.setAlpha(0)
        if self.flash:
            hl = QColor(theme.ACCENT)
            color = QColor(
                int(color.red() + (hl.red() - color.red()) * self.flash * 0.5),
                int(color.green() + (hl.green() - color.green()) * self.flash * 0.5),
                int(color.blue() + (hl.blue() - color.blue()) * self.flash * 0.5),
                max(color.alpha(), int(255 * self.flash * 0.5)),
            )
        p.setBrush(color)
        p.drawRoundedRect(QRectF(self.rect()), 14, 14)


class MessageRow(QWidget):
    """One message: optional sender avatar, then the bubble on its side."""

    def __init__(self, ctx: Context, item: MessageItem, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.item = item
        self.run_start = True
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(12, 1, 12, 1)
        self.lay.setSpacing(8)
        self.avatar = None
        if ctx.show_names and not item.out:
            self.avatar = QLabel()
            self.avatar.setFixedSize(GROUP_AVATAR, GROUP_AVATAR)
            self.avatar.setAlignment(Qt.AlignTop)
            self.lay.addWidget(self.avatar, 0, Qt.AlignTop)
        self.bubble = Bubble(ctx, item)
        if item.out:
            self.lay.addStretch(1)
            self.lay.addWidget(self.bubble)
        else:
            self.lay.addWidget(self.bubble)
            self.lay.addStretch(1)
        self.paint_avatar()

    @property
    def day(self) -> date:
        return local(self.item.date).date()

    def paint_avatar(self) -> None:
        if self.avatar is None:
            return
        if self.run_start:
            self.avatar.setPixmap(self.ctx.avatars.pixmap(
                self.item.sender_id or 0, self.item.sender_name, GROUP_AVATAR, self.devicePixelRatioF()))
        else:
            self.avatar.clear()

    def set_run_start(self, start: bool) -> None:
        if start == self.run_start:
            return
        self.run_start = start
        self.bubble.set_run_start(start)
        self.lay.setContentsMargins(12, 6 if start else 1, 12, 1)
        self.paint_avatar()

    def replace(self, item: MessageItem) -> None:
        self.item = item
        old = self.bubble
        self.bubble = Bubble(self.ctx, item)
        self.bubble.set_run_start(self.run_start)
        self.lay.replaceWidget(old, self.bubble)
        old.deleteLater()
        if self.bubble.media_view:
            self.bubble.media_view.load()

    def fit(self, max_w: int) -> None:
        self.bubble.fit(max_w)


class Pill(QWidget):
    """Centered label: day separators, service messages, unread marker."""

    def __init__(self, text: str, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8 if kind != "service" else 3, 12, 4)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignCenter)
        if kind == "unread":
            self.label.setStyleSheet(f"color: {theme.TEXT_DIM}; background: #1c222c; padding: 4px; border-radius: 6px;")
            lay.addWidget(self.label, 1)
        else:
            self.label.setStyleSheet("background: rgba(40,46,58,0.85); border-radius: 10px; padding: 3px 10px;"
                                     f"color: {theme.TEXT if kind == 'day' else theme.TEXT_DIM};")
            lay.addStretch(1)
            lay.addWidget(self.label)
            lay.addStretch(1)


class DayRow(Pill):
    def __init__(self, day: date, parent=None):
        super().__init__(day_title(day), "day", parent)
        self.day = day


class ServiceRow(Pill):
    def __init__(self, item: MessageItem, parent=None):
        super().__init__(item.service, "service", parent)
        self.item = item

    @property
    def day(self) -> date:
        return local(self.item.date).date()

    def set_run_start(self, _start: bool) -> None:
        pass

    def fit(self, max_w: int) -> None:
        self.label.setMaximumWidth(max_w)

    def replace(self, item: MessageItem) -> None:
        self.item = item
        self.label.setText(item.service)


# --- the list --------------------------------------------------------------


class MessageList(QScrollArea):
    need_older = Signal()
    reached_bottom = Signal()
    jump_requested = Signal(object)  # msg id
    media_clicked = Signal(object, object)  # MessageItem, Bubble
    link_clicked = Signal(str)
    context_requested = Signal(object, object, QPoint)  # MessageItem, Bubble, global pos
    reply_requested = Signal(object)

    def __init__(self, ctx: Context, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        ctx.list = self
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = QWidget(objectName="MessageCanvas")
        self.vbox = QVBoxLayout(self.canvas)
        self.vbox.setContentsMargins(0, 8, 0, 10)
        self.vbox.setSpacing(2)
        self.vbox.addStretch(1)
        self.setWidget(self.canvas)

        self.entries: list[QWidget] = []
        self.rows: dict[int, MessageRow | ServiceRow] = {}
        self.unread_marker: Pill | None = None
        self.at_start = False
        self.loading_older = False
        self.stick_bottom = True
        self._anchor: int | None = None
        self._pending_new = 0

        bar = self.verticalScrollBar()
        bar.setSingleStep(30)
        bar.rangeChanged.connect(self._range_changed)
        bar.valueChanged.connect(self._scrolled)

        ctx.avatars.ready.connect(self._avatar_ready)

        self.jump = QToolButton(self.viewport(), objectName="JumpDown", text="↓")
        self.jump.setFixedSize(40, 40)
        self.jump.setCursor(Qt.PointingHandCursor)
        self.jump.clicked.connect(self.scroll_to_bottom)
        self.jump.hide()
        self._fit_timer = QTimer(self, singleShot=True, interval=30, timeout=self._refit)

    # --- building

    def _make(self, item: MessageItem) -> QWidget:
        row = ServiceRow(item) if item.service else MessageRow(self.ctx, item)
        self.rows[item.id] = row
        return row

    def _insert(self, index: int, widget: QWidget) -> None:
        self.entries.insert(index, widget)
        self.vbox.insertWidget(index + 1, widget)  # +1: the top stretch

    def _remove_entry(self, widget: QWidget) -> None:
        self.entries.remove(widget)
        self.vbox.removeWidget(widget)
        widget.deleteLater()

    def message_entries(self) -> list:
        return [e for e in self.entries if isinstance(e, (MessageRow, ServiceRow))]

    def set_messages(self, items: list[MessageItem], first_unread: int | None = None) -> None:
        self.stick_bottom = True
        self.at_start = len(items) == 0
        prev_day = None
        for item in items:
            day = local(item.date).date()
            if day != prev_day:
                self._insert(len(self.entries), DayRow(day))
                prev_day = day
            if first_unread is not None and item.id == first_unread:
                self.unread_marker = Pill("Непрочитанные сообщения", "unread")
                self._insert(len(self.entries), self.unread_marker)
                self.stick_bottom = False
            self._insert(len(self.entries), self._make(item))
        self._update_runs()
        self._load_media(reversed(items))
        if self.unread_marker is not None:
            QTimer.singleShot(0, lambda: self._show_unread_marker())

    def _show_unread_marker(self) -> None:
        if self.unread_marker is not None:
            self.verticalScrollBar().setValue(max(0, self.unread_marker.y() - 60))

    def prepend(self, items: list[MessageItem]) -> None:
        items = [i for i in items if i.id not in self.rows]
        if not items:
            return
        bar = self.verticalScrollBar()
        self._anchor = bar.maximum() - bar.value()
        new: list[QWidget] = []
        prev_day = None
        for item in items:
            day = local(item.date).date()
            if day != prev_day:
                new.append(DayRow(day))
                prev_day = day
            new.append(self._make(item))
        if self.entries and isinstance(self.entries[0], DayRow) and self.entries[0].day == prev_day:
            self._remove_entry(self.entries[0])
        for i, w in enumerate(new):
            self._insert(i, w)
        self._update_runs()
        self._load_media(reversed(items))
        QTimer.singleShot(120, lambda: setattr(self, "_anchor", None))

    def add(self, item: MessageItem) -> bool:
        """Insert a new message or replace an existing one. Returns True when it was new."""
        existing = self.rows.get(item.id)
        if existing is not None:
            existing.replace(item)
            return False
        msgs = self.message_entries()
        if msgs and item.id < msgs[-1].item.id:
            # out-of-order arrival: place after the closest older message
            older = [m for m in msgs if m.item.id < item.id]
            if not older:
                return False  # older than the loaded window; it will come with history
            index = self.entries.index(older[-1]) + 1
            self._insert(index, self._make(item))
        else:
            day = local(item.date).date()
            if not msgs or msgs[-1].day != day:
                self._insert(len(self.entries), DayRow(day))
            self._insert(len(self.entries), self._make(item))
            if not item.out and not self.stick_bottom:
                self._pending_new += 1
                self._update_jump()
        if item.out:
            self.stick_bottom = True
        self._update_runs()
        self._load_media([item])
        return True

    def remove(self, ids: list[int]) -> None:
        for msg_id in ids:
            row = self.rows.pop(msg_id, None)
            if row is not None:
                self._remove_entry(row)
        # drop separators left without messages under them
        cleaned = True
        while cleaned:
            cleaned = False
            for i, e in enumerate(self.entries):
                nxt = self.entries[i + 1] if i + 1 < len(self.entries) else None
                if isinstance(e, Pill) and not isinstance(e, ServiceRow) and (
                        nxt is None or (isinstance(nxt, DayRow))):
                    if e is self.unread_marker:
                        self.unread_marker = None
                    self._remove_entry(e)
                    cleaned = True
                    break
        self._update_runs()

    def refresh_read(self) -> None:
        for row in self.rows.values():
            if isinstance(row, MessageRow) and row.item.out:
                row.bubble.refresh_meta()

    def oldest_id(self) -> int:
        msgs = self.message_entries()
        return msgs[0].item.id if msgs else 0

    def newest_id(self) -> int:
        msgs = self.message_entries()
        return msgs[-1].item.id if msgs else 0

    def last_own_text(self) -> MessageItem | None:
        for e in reversed(self.message_entries()):
            if isinstance(e, MessageRow) and e.item.out and e.item.text:
                return e.item
        return None

    def _update_runs(self) -> None:
        prev = None
        for e in self.entries:
            if isinstance(e, MessageRow):
                start = not (
                    isinstance(prev, MessageRow)
                    and prev.item.sender_id == e.item.sender_id
                    and prev.item.out == e.item.out
                    and (e.item.date - prev.item.date).total_seconds() < 600
                )
                e.set_run_start(start)
            prev = e

    def _avatar_ready(self, peer_id) -> None:
        if not isValid(self):
            return
        for row in self.rows.values():
            if isinstance(row, MessageRow) and row.item.sender_id == peer_id and row.run_start:
                row.paint_avatar()

    def _load_media(self, items) -> None:
        for item in items:
            row = self.rows.get(item.id)
            if isinstance(row, MessageRow) and row.bubble.media_view:
                row.bubble.media_view.load()

    # --- geometry & scrolling

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_jump()
        width = self.viewport().width()
        avatar = GROUP_AVATAR + 8 if self.ctx.show_names else 0
        new_max = max(220, min(int(width * 0.72), 640) - avatar)
        if new_max != self.ctx.max_width:
            self.ctx.max_width = new_max
            self._fit_timer.start()

    def _refit(self) -> None:
        for e in self.entries:
            if hasattr(e, "fit"):
                e.fit(self.ctx.max_width)

    def _place_jump(self) -> None:
        vp = self.viewport()
        self.jump.move(vp.width() - self.jump.width() - 16, vp.height() - self.jump.height() - 16)

    def _range_changed(self, _min: int, maximum: int) -> None:
        bar = self.verticalScrollBar()
        if self._anchor is not None:
            bar.setValue(maximum - self._anchor)
        elif self.stick_bottom:
            bar.setValue(maximum)

    def _scrolled(self, value: int) -> None:
        bar = self.verticalScrollBar()
        if self._anchor is None:
            was = self.stick_bottom
            self.stick_bottom = value >= bar.maximum() - 30
            if self.stick_bottom and not was:
                self._pending_new = 0
                self.reached_bottom.emit()
        self._update_jump()
        if value < 400 and not self.at_start and not self.loading_older and self.entries and self._anchor is None:
            self.need_older.emit()

    def _update_jump(self) -> None:
        show = not self.stick_bottom
        self.jump.setVisible(show)
        self.jump.setText(f"↓ {self._pending_new}" if self._pending_new else "↓")
        self.jump.setFixedWidth(40 if not self._pending_new else 64)
        self._place_jump()

    def scroll_to_bottom(self) -> None:
        self.stick_bottom = True
        self._pending_new = 0
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        self._update_jump()
        self.reached_bottom.emit()

    def show_message(self, msg_id: int) -> bool:
        row = self.rows.get(msg_id)
        if row is None:
            return False
        self.stick_bottom = False
        self.ensureWidgetVisible(row, 0, self.viewport().height() // 3)
        if isinstance(row, MessageRow):
            row.bubble.start_flash()
        return True

    # --- interaction

    def bubble_at(self, global_pos: QPoint) -> Bubble | None:
        w = self.canvas.childAt(self.canvas.mapFromGlobal(global_pos))
        while w is not None and not isinstance(w, Bubble):
            w = w.parentWidget()
        return w

    def contextMenuEvent(self, e):
        bubble = self.bubble_at(e.globalPos())
        if bubble is not None:
            self.context_requested.emit(bubble.item, bubble, e.globalPos())

    def mouseDoubleClickEvent(self, e):
        bubble = self.bubble_at(e.globalPosition().toPoint())
        if bubble is not None:
            self.reply_requested.emit(bubble.item)
        else:
            super().mouseDoubleClickEvent(e)


def _esc(text: str) -> str:
    from html import escape

    return escape(text, quote=False)


def _compact(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(n)
