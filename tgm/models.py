"""Plain data the UI works with, built from Telethon objects.

The UI never touches Telethon types directly: everything it shows comes
from ChatItem / MessageItem, which keeps widgets simple and testable.
"""

from __future__ import annotations

import html
import time
from dataclasses import dataclass, field
from datetime import datetime

from telethon import utils
from telethon.helpers import add_surrogate, del_surrogate
from telethon.tl import types as t


@dataclass
class MediaInfo:
    kind: str  # photo sticker video gif round voice audio document webpage geo contact poll other
    width: int = 0
    height: int = 0
    file_name: str = ""
    size: int = 0
    mime: str = ""
    duration: float = 0
    stripped: bytes | None = None  # tiny inline JPEG preview, already expanded
    has_thumb: bool = False
    emoji: str = ""  # sticker alt
    title: str = ""  # webpage title / audio title / contact name / poll question
    subtitle: str = ""
    url: str = ""
    spoiler: bool = False


@dataclass
class ReplyInfo:
    msg_id: int
    sender: str = ""
    text: str = ""


@dataclass
class MessageItem:
    id: int
    chat_id: int
    date: datetime
    out: bool
    sender_id: int | None
    sender_name: str
    text: str  # plain text, used for copy / edit / previews
    html: str  # rendered for QLabel
    media: MediaInfo | None = None
    reply: ReplyInfo | None = None
    forward: str = ""
    via_bot: str = ""
    edited: bool = False
    service: str = ""  # non-empty for service messages, which have no bubble
    views: int | None = None
    reactions: str = ""
    grouped_id: int | None = None
    post_author: str = ""

    @property
    def preview(self) -> str:
        """One-line text for chat list and reply quotes."""
        if self.service:
            return self.service
        body = " ".join(self.text.split())
        if self.media:
            label = media_label(self.media)
            return f"{label}, {body}" if body else label
        return body


@dataclass
class ChatItem:
    peer_id: int
    title: str
    kind: str  # user bot group channel self
    entity: object = field(repr=False, default=None)
    username: str = ""
    photo_id: int | None = None
    is_contact: bool = False
    verified: bool = False
    last: MessageItem | None = None
    unread: int = 0
    mentions: int = 0
    read_outbox_max_id: int = 0
    read_inbox_max_id: int = 0
    pinned: bool = False
    pin_rank: int = 0
    archived: bool = False
    muted_until: int = 0
    unread_mark: bool = False
    in_dialogs: bool = True  # False for global search results
    typing: str = ""  # transient "… печатает"

    @property
    def muted(self) -> bool:
        return self.muted_until > time.time()

    @property
    def sort_date(self) -> float:
        return self.last.date.timestamp() if self.last else 0.0

    @property
    def can_write(self) -> bool:
        entity = self.entity
        if isinstance(entity, t.Channel) and entity.broadcast:
            return bool(entity.creator or entity.admin_rights)
        if isinstance(entity, (t.Channel, t.Chat)) and getattr(entity, "left", False):
            return False
        return True


# --- entity → chat ---------------------------------------------------------


def display_name(entity) -> str:
    if entity is None:
        return "Удалённый аккаунт"
    if isinstance(entity, t.User):
        if entity.deleted:
            return "Удалённый аккаунт"
        name = " ".join(p for p in (entity.first_name, entity.last_name) if p)
        return name or (entity.username and "@" + entity.username) or str(entity.id)
    return getattr(entity, "title", "") or "Без названия"


def entity_kind(entity) -> str:
    if isinstance(entity, t.User):
        if entity.is_self:
            return "self"
        return "bot" if entity.bot else "user"
    if isinstance(entity, t.Channel) and entity.broadcast:
        return "channel"
    return "group"


def entity_photo_id(entity) -> int | None:
    photo = getattr(entity, "photo", None)
    return getattr(photo, "photo_id", None)


def chat_from_entity(entity) -> ChatItem:
    kind = entity_kind(entity)
    return ChatItem(
        peer_id=utils.get_peer_id(entity),
        title="Избранное" if kind == "self" else display_name(entity),
        kind=kind,
        entity=entity,
        username=getattr(entity, "username", None) or "",
        photo_id=entity_photo_id(entity),
        is_contact=bool(getattr(entity, "contact", False)),
        verified=bool(getattr(entity, "verified", False)),
    )


def chat_from_dialog(dialog, rank: int = 0) -> ChatItem:
    """`dialog` is a telethon.tl.custom.Dialog."""
    chat = chat_from_entity(dialog.entity)
    raw = dialog.dialog
    chat.unread = raw.unread_count
    chat.mentions = raw.unread_mentions_count
    chat.unread_mark = bool(raw.unread_mark)
    chat.read_outbox_max_id = raw.read_outbox_max_id
    chat.read_inbox_max_id = raw.read_inbox_max_id
    chat.pinned = bool(raw.pinned)
    chat.pin_rank = rank
    chat.archived = dialog.archived
    chat.muted_until = mute_until(raw.notify_settings)
    if dialog.message is not None:
        chat.last = message_from_telethon(dialog.message)
    return chat


def mute_until(settings) -> int:
    """Unix time until which notifications are off. Telethon turns the field into a datetime."""
    value = getattr(settings, "mute_until", None)
    if isinstance(value, datetime):
        return int(value.timestamp())
    return int(value or 0)


# --- messages --------------------------------------------------------------


def message_from_telethon(msg) -> MessageItem:
    """`msg` is a telethon Message (custom), with sender/chat already resolved when possible."""
    chat_id = utils.get_peer_id(msg.peer_id)
    sender = msg.sender
    sender_id = msg.sender_id
    if msg.post and not sender:
        sender = msg.chat
    sender_name = display_name(sender) if (sender is not None or sender_id) else ""

    item = MessageItem(
        id=msg.id,
        chat_id=chat_id,
        date=msg.date,
        out=bool(msg.out),
        sender_id=sender_id,
        sender_name=sender_name,
        text="",
        html="",
    )

    if isinstance(msg, t.MessageService) or getattr(msg, "action", None):
        item.service = service_text(msg, sender_name)
        return item

    item.text = msg.message or ""
    item.html = entities_to_html(item.text, msg.entities or [])
    item.media = media_from_telethon(msg.media)
    item.edited = bool(msg.edit_date and not msg.edit_hide)
    item.views = msg.views
    item.grouped_id = msg.grouped_id
    item.post_author = msg.post_author or ""
    if msg.reply_to and getattr(msg.reply_to, "reply_to_msg_id", None):
        item.reply = ReplyInfo(msg.reply_to.reply_to_msg_id)
        quote = getattr(msg.reply_to, "quote_text", None)
        if quote:
            item.reply.text = quote
    if msg.fwd_from:
        item.forward = forward_name(msg)
    if msg.via_bot_id and msg.via_bot:
        item.via_bot = getattr(msg.via_bot, "username", "") or ""
    item.reactions = reactions_text(msg.reactions)
    return item


def forward_name(msg) -> str:
    fwd = msg.fwd_from
    if fwd.from_name:
        return fwd.from_name
    entity = getattr(msg.forward, "sender", None) or getattr(msg.forward, "chat", None)
    if entity is not None:
        return display_name(entity)
    return "скрытый пользователь"


def reactions_text(reactions) -> str:
    if not reactions or not reactions.results:
        return ""
    parts = []
    for r in reactions.results:
        emoji = getattr(r.reaction, "emoticon", None) or ("⭐" if isinstance(r.reaction, t.ReactionPaid) else "❔")
        parts.append(f"{emoji} {r.count}" if r.count > 1 else emoji)
    return "  ".join(parts)


def media_from_telethon(media) -> MediaInfo | None:
    if media is None or isinstance(media, t.MessageMediaEmpty):
        return None
    if isinstance(media, t.MessageMediaPhoto):
        photo = media.photo
        if not isinstance(photo, t.Photo):
            return MediaInfo("other", title="Фото недоступно")
        w, h = largest_size(photo.sizes)
        return MediaInfo("photo", width=w, height=h, stripped=stripped_jpeg(photo.sizes), spoiler=bool(media.spoiler))
    if isinstance(media, t.MessageMediaDocument):
        doc = media.document
        if not isinstance(doc, t.Document):
            return MediaInfo("other", title="Файл недоступен")
        return document_info(doc, media)
    if isinstance(media, t.MessageMediaWebPage):
        page = media.webpage
        if isinstance(page, t.WebPage):
            return MediaInfo(
                "webpage",
                title=page.title or page.site_name or "",
                subtitle=page.description or "",
                url=page.url,
            )
        return None
    if isinstance(media, (t.MessageMediaGeo, t.MessageMediaGeoLive, t.MessageMediaVenue)):
        geo = media.geo
        title = getattr(media, "title", "") or "Геопозиция"
        url = f"https://www.openstreetmap.org/?mlat={geo.lat}&mlon={geo.long}#map=16/{geo.lat}/{geo.long}" if isinstance(geo, t.GeoPoint) else ""
        return MediaInfo("geo", title=title, url=url)
    if isinstance(media, t.MessageMediaContact):
        name = " ".join(p for p in (media.first_name, media.last_name) if p)
        return MediaInfo("contact", title=name, subtitle=media.phone_number or "")
    if isinstance(media, t.MessageMediaPoll):
        question = media.poll.question
        text = getattr(question, "text", question)
        options = [getattr(a.text, "text", a.text) for a in media.poll.answers]
        return MediaInfo("poll", title=text, subtitle="\n".join("○ " + o for o in options))
    if isinstance(media, t.MessageMediaDice):
        return MediaInfo("other", title=f"{media.emoticon} {media.value}")
    return MediaInfo("other", title="Неподдерживаемое вложение")


def document_info(doc, media=None) -> MediaInfo:
    info = MediaInfo("document", mime=doc.mime_type or "", size=doc.size or 0, has_thumb=bool(doc.thumbs))
    info.stripped = stripped_jpeg(doc.thumbs or [])
    is_animated = False
    for attr in doc.attributes:
        if isinstance(attr, t.DocumentAttributeFilename):
            info.file_name = attr.file_name
        elif isinstance(attr, t.DocumentAttributeImageSize):
            info.width, info.height = attr.w, attr.h
        elif isinstance(attr, t.DocumentAttributeVideo):
            info.width, info.height, info.duration = attr.w, attr.h, attr.duration
            info.kind = "round" if attr.round_message else "video"
        elif isinstance(attr, t.DocumentAttributeAudio):
            info.duration = attr.duration
            info.kind = "voice" if attr.voice else "audio"
            info.title = attr.title or ""
            info.subtitle = attr.performer or ""
        elif isinstance(attr, t.DocumentAttributeAnimated):
            is_animated = True
        elif isinstance(attr, t.DocumentAttributeSticker):
            info.emoji = attr.alt or ""
    if any(isinstance(a, t.DocumentAttributeSticker) for a in doc.attributes):
        info.kind = "sticker"
        if not info.width:
            info.width = info.height = 512
    elif is_animated and info.kind == "video":
        info.kind = "gif"
    if media is not None and getattr(media, "spoiler", False):
        info.spoiler = True
    return info


def largest_size(sizes) -> tuple[int, int]:
    best = (0, 0)
    for s in sizes:
        w, h = getattr(s, "w", 0), getattr(s, "h", 0)
        if w * h > best[0] * best[1]:
            best = (w, h)
    return best


def stripped_jpeg(sizes) -> bytes | None:
    for s in sizes:
        if isinstance(s, t.PhotoStrippedSize):
            return utils.stripped_photo_to_jpg(s.bytes)
    return None


def pick_photo_size(sizes, target: int = 800):
    """Smallest downloadable size whose long side reaches `target`, else the largest."""
    usable = [s for s in sizes if isinstance(s, (t.PhotoSize, t.PhotoSizeProgressive, t.PhotoCachedSize))]
    if not usable:
        return None
    usable.sort(key=lambda s: max(s.w, s.h))
    for s in usable:
        if max(s.w, s.h) >= target:
            return s
    return usable[-1]


def media_label(media: MediaInfo) -> str:
    match media.kind:
        case "photo":
            return "Фото"
        case "sticker":
            return f"{media.emoji} Стикер".strip()
        case "video":
            return "Видео"
        case "round":
            return "Видеосообщение"
        case "gif":
            return "GIF"
        case "voice":
            return "Голосовое сообщение"
        case "audio":
            return " — ".join(p for p in (media.subtitle, media.title) if p) or "Аудио"
        case "document":
            return media.file_name or "Файл"
        case "geo":
            return media.title or "Геопозиция"
        case "contact":
            return "Контакт"
        case "poll":
            return f"Опрос: {media.title}"
        case "webpage":
            return media.title or "Ссылка"
    return media.title or "Вложение"


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024 or unit == "ГБ":
            return f"{value:.0f} {unit}" if unit == "Б" else f"{value:.1f} {unit}"
        value /= 1024
    return ""


def human_duration(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02}:{s % 60:02}" if s >= 3600 else f"{s // 60}:{s % 60:02}"


# --- service messages ------------------------------------------------------


def service_text(msg, actor: str) -> str:
    a = msg.action
    who = actor or "Кто-то"
    if isinstance(a, t.MessageActionChatCreate):
        return f"{who} создаёт группу «{a.title}»"
    if isinstance(a, t.MessageActionChannelCreate):
        return f"Канал «{a.title}» создан"
    if isinstance(a, t.MessageActionChatEditTitle):
        return f"{who} меняет название на «{a.title}»"
    if isinstance(a, t.MessageActionChatEditPhoto):
        return f"{who} обновляет фото"
    if isinstance(a, t.MessageActionChatDeletePhoto):
        return f"{who} удаляет фото"
    if isinstance(a, t.MessageActionChatAddUser):
        if msg.sender_id in a.users:
            return f"{who} присоединяется"
        return f"{who} добавляет участников"
    if isinstance(a, t.MessageActionChatDeleteUser):
        if a.user_id == msg.sender_id:
            return f"{who} покидает группу"
        return f"{who} удаляет участника"
    if isinstance(a, t.MessageActionChatJoinedByLink):
        return f"{who} присоединяется по ссылке"
    if isinstance(a, t.MessageActionChatJoinedByRequest):
        return f"{who} принят(а) в группу"
    if isinstance(a, t.MessageActionPinMessage):
        return f"{who} закрепляет сообщение"
    if isinstance(a, t.MessageActionHistoryClear):
        return "История очищена"
    if isinstance(a, t.MessageActionPhoneCall):
        kind = "Видеозвонок" if a.video else "Звонок"
        if a.duration:
            return f"{kind}, {human_duration(a.duration)}"
        return f"{kind} (пропущен)" if not msg.out else f"{kind} (отменён)"
    if isinstance(a, t.MessageActionGroupCall):
        return "Видеочат завершён" if a.duration else "Видеочат начат"
    if isinstance(a, t.MessageActionScreenshotTaken):
        return f"{who} делает скриншот"
    if isinstance(a, t.MessageActionContactSignUp):
        return f"{who} теперь в Telegram"
    if isinstance(a, t.MessageActionChatMigrateTo) or isinstance(a, t.MessageActionChannelMigrateFrom):
        return "Группа преобразована в супергруппу"
    if isinstance(a, t.MessageActionSetMessagesTTL):
        return "Изменён таймер автоудаления"
    if isinstance(a, t.MessageActionTopicCreate):
        return f"Создана тема «{a.title}»"
    if isinstance(a, t.MessageActionCustomAction):
        return a.message
    return "Служебное сообщение"


# --- formatting entities → Qt rich text ------------------------------------

_PEER_COLORS = ["#e17076", "#eda86c", "#a695e7", "#7bc862", "#6ec9cb", "#65aadd", "#ee7aae"]


def peer_color(peer_id: int | None) -> str:
    return _PEER_COLORS[abs(peer_id or 0) % len(_PEER_COLORS)]


def _wrap(entity, inner: str, text: str) -> str:
    match entity:
        case t.MessageEntityBold():
            return f"<b>{inner}</b>"
        case t.MessageEntityItalic():
            return f"<i>{inner}</i>"
        case t.MessageEntityUnderline():
            return f"<u>{inner}</u>"
        case t.MessageEntityStrike():
            return f"<s>{inner}</s>"
        case t.MessageEntityCode():
            return f'<code style="background:rgba(127,127,127,0.18)">{inner}</code>'
        case t.MessageEntityPre():
            return f'<pre style="background:rgba(127,127,127,0.18)">{inner}</pre>'
        case t.MessageEntityTextUrl():
            return f'<a href="{html.escape(entity.url, quote=True)}">{inner}</a>'
        case t.MessageEntityUrl():
            url = text if "://" in text else "https://" + text
            return f'<a href="{html.escape(url, quote=True)}">{inner}</a>'
        case t.MessageEntityEmail():
            return f'<a href="mailto:{html.escape(text, quote=True)}">{inner}</a>'
        case t.MessageEntityPhone():
            return f'<a href="tel:{html.escape(text, quote=True)}">{inner}</a>'
        case t.MessageEntityMention():
            return f'<a href="tgm-user:{html.escape(text.lstrip("@"), quote=True)}">{inner}</a>'
        case t.MessageEntityMentionName():
            return f'<a href="tgm-peer:{entity.user_id}">{inner}</a>'
        case t.MessageEntityHashtag() | t.MessageEntityCashtag() | t.MessageEntityBotCommand():
            return f'<span style="color:#6ab2f2">{inner}</span>'
        case t.MessageEntitySpoiler():
            return f'<span style="background:#5a6573;color:#5a6573">{inner}</span>'
        case t.MessageEntityBlockquote():
            return f'<blockquote style="margin-left:8px">{inner}</blockquote>'
    return inner


def entities_to_html(text: str, entities) -> str:
    """Render message text with its entities. Offsets are in UTF-16 code units."""
    if not text:
        return ""
    src = add_surrogate(text)
    # Opening/closing events, longest entity opens first so nesting stays valid.
    usable = [e for e in entities if e.length > 0 and e.offset < len(src)]
    usable.sort(key=lambda e: (e.offset, -e.length))

    def render(start: int, end: int, ents: list) -> str:
        out: list[str] = []
        pos = start
        i = 0
        while i < len(ents):
            e = ents[i]
            e_end = min(e.offset + e.length, end)
            if e.offset < pos:  # overlapping, not properly nested: drop
                i += 1
                continue
            out.append(_plain(src[pos:e.offset]))
            children = []
            j = i + 1
            while j < len(ents) and ents[j].offset < e_end:
                children.append(ents[j])
                j += 1
            inner = render(e.offset, e_end, children)
            out.append(_wrap(e, inner, del_surrogate(src[e.offset:e_end])))
            pos = e_end
            i = j
        out.append(_plain(src[pos:end]))
        return "".join(out)

    return render(0, len(src), usable)


def _plain(chunk: str) -> str:
    return html.escape(del_surrogate(chunk), quote=False).replace("\n", "<br>")
