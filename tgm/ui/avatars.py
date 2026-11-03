"""Round avatars: downloaded on first paint, initials until then."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPixmap

from ..models import peer_color
from ..tasks import spawn


def initials(title: str) -> str:
    words = [w for w in title.replace("@", "").split() if w[:1].isalnum()]
    if not words:
        return title[:1].upper() or "?"
    first = words[0][0]
    second = words[1][0] if len(words) > 1 else ""
    return (first + second).upper()


def circle(image: QImage, size: int, dpr: float) -> QPixmap:
    px = int(size * dpr)
    scaled = image.scaled(px, px, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addEllipse(QRectF(0, 0, px, px))
    p.setClipPath(path)
    p.drawImage((px - scaled.width()) // 2, (px - scaled.height()) // 2, scaled)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def placeholder(peer_id: int, title: str, size: int, dpr: float, saved: bool = False) -> QPixmap:
    px = int(size * dpr)
    out = QPixmap(px, px)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#5b8def" if saved else peer_color(peer_id)))
    p.drawEllipse(QRectF(0, 0, px, px))
    p.setPen(QColor("white"))
    font = QFont()
    font.setPixelSize(int(px * (0.42 if saved else 0.38)))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, px, px), Qt.AlignCenter, "★" if saved else initials(title))
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


class AvatarStore(QObject):
    ready = Signal(object)  # peer_id

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._images: dict[int, QImage | None] = {}  # None = no photo / failed
        self._pixmaps: dict[tuple, QPixmap] = {}
        self._pending: set[int] = set()

    def pixmap(self, peer_id: int, title: str, size: int, dpr: float = 1.0, saved: bool = False) -> QPixmap:
        key = (peer_id, size, dpr)
        cached = self._pixmaps.get(key)
        if cached is not None:
            return cached
        image = self._images.get(peer_id)
        if image is not None and not saved:
            pm = circle(image, size, dpr)
            self._pixmaps[key] = pm
            return pm
        if peer_id not in self._images and not saved:
            self._request(peer_id)
        return placeholder(peer_id, title, size, dpr, saved)

    def invalidate(self, peer_id: int) -> None:
        self._images.pop(peer_id, None)
        for key in [k for k in self._pixmaps if k[0] == peer_id]:
            del self._pixmaps[key]

    def _request(self, peer_id: int) -> None:
        if peer_id in self._pending:
            return
        self._pending.add(peer_id)

        async def load():
            try:
                path = await self.service.avatar(peer_id)
                image = QImage(str(path)) if path else None
                self._images[peer_id] = image if image is not None and not image.isNull() else None
            except Exception:
                self._images[peer_id] = None
                raise
            finally:
                self._pending.discard(peer_id)
            if self._images[peer_id] is not None:
                self.ready.emit(peer_id)

        spawn(load(), quiet=True)
