"""Unit tests for the parts that do not need a network or a display."""

from __future__ import annotations

import re
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from telethon.tl import types as t

from tgm.config import ConfigError, load_settings, parse_proxy, read_env_file
from tgm.folders import ALL_ID, ARCHIVE_ID, Folder, folder_from_filter
from tgm.models import ChatItem, MessageItem, entities_to_html, human_size, mute_until
from tgm.service import plural, presence_text
from tgm.ui.fmt import day_title, list_time

HASH = "0123456789abcdef0123456789abcdef"


class ConfigTests(unittest.TestCase):
    def env_file(self, text: str) -> Path:
        d = Path(tempfile.mkdtemp())
        (d / ".env").write_text(text)
        return d / ".env"

    def test_reads_quotes_comments_and_export(self):
        path = self.env_file('# c\nexport TG_API_ID="123"\nTG_API_HASH=\'%s\'\n\nbroken line\n' % HASH)
        self.assertEqual(read_env_file(path), {"TG_API_ID": "123", "TG_API_HASH": HASH})

    def test_environment_overrides_file(self):
        path = self.env_file(f"TG_API_ID=1\nTG_API_HASH={HASH}\n")
        s = load_settings(path, {"TG_API_ID": "42", "TG_DATA_DIR": "/tmp/x"})
        self.assertEqual(s.api_id, 42)
        self.assertEqual(s.data_dir, Path("/tmp/x"))
        self.assertTrue(s.notify)

    def test_missing_or_bad_keys(self):
        with self.assertRaises(ConfigError):
            load_settings(self.env_file(""), {})
        with self.assertRaises(ConfigError):
            load_settings(self.env_file("TG_API_ID=abc\nTG_API_HASH=%s" % HASH), {})
        with self.assertRaises(ConfigError):
            load_settings(self.env_file("TG_API_ID=1\nTG_API_HASH=short"), {})

    def test_secret_not_in_repr(self):
        s = load_settings(self.env_file(f"TG_API_ID=1\nTG_API_HASH={HASH}\nTG_SESSION=SECRET"), {})
        self.assertNotIn(HASH, repr(s))
        self.assertNotIn("SECRET", repr(s))

    def test_proxies(self):
        self.assertIsNone(parse_proxy(""))
        p = parse_proxy("socks5h://u:p%40ss@127.0.0.1:1080")
        self.assertEqual((p.kind, p.host, p.port, p.username, p.password), ("socks5", "127.0.0.1", 1080, "u", "p@ss"))
        self.assertEqual(parse_proxy("127.0.0.1:9050").kind, "socks5")
        m = parse_proxy("https://t.me/proxy?server=127.0.0.1&port=1443&secret=dd00ff")
        self.assertEqual((m.kind, m.port, m.secret), ("mtproto", 1443, "dd00ff"))
        self.assertEqual(parse_proxy("tg://proxy?server=h&port=1&secret=ab").kind, "mtproto")
        for bad in ("ftp://h:1", "socks5://h", "https://t.me/proxy?server=h&port=x&secret=a", "socks5://h:70000"):
            with self.assertRaises(ConfigError, msg=bad):
                parse_proxy(bad)

    def test_fake_tls_secret_rejected(self):
        with self.assertRaises(ConfigError):
            parse_proxy("tg://proxy?server=h&port=1&secret=ee00").telethon_kwargs()


class HtmlTests(unittest.TestCase):
    def test_plain_text_is_escaped(self):
        self.assertEqual(entities_to_html("a<b>&\nc", []), "a&lt;b&gt;&amp;<br>c")

    def test_nested_entities(self):
        text = "bold italic"
        ents = [t.MessageEntityBold(0, 11), t.MessageEntityItalic(5, 6)]
        self.assertEqual(entities_to_html(text, ents), "<b>bold <i>italic</i></b>")

    def test_utf16_offsets_with_emoji(self):
        text = "😀 hi"  # the emoji is two UTF-16 units
        html = entities_to_html(text, [t.MessageEntityBold(3, 2)])
        self.assertEqual(html, "😀 <b>hi</b>")

    def test_links_and_mentions(self):
        html = entities_to_html("x.com @bob", [t.MessageEntityUrl(0, 5), t.MessageEntityMention(6, 4)])
        self.assertIn('<a href="https://x.com">x.com</a>', html)
        self.assertIn('<a href="tgm-user:bob">@bob</a>', html)

    def test_text_url_is_escaped(self):
        html = entities_to_html("go", [t.MessageEntityTextUrl(0, 2, url='https://a/"><script>')])
        self.assertNotIn("<script>", html)

    def test_overlapping_entities_do_not_break_markup(self):
        html = entities_to_html("abcdef", [t.MessageEntityBold(0, 4), t.MessageEntityItalic(2, 4)])
        self.assertEqual(html.count("<b>"), html.count("</b>"))
        self.assertEqual(re.sub(r"<[^>]+>", "", html), "abcdef")


def chat(peer_id=1, kind="user", **kw) -> ChatItem:
    c = ChatItem(peer_id=peer_id, title=f"c{peer_id}", kind=kind)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def msg(i: int, minutes_ago: int = 0) -> MessageItem:
    d = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return MessageItem(id=i, chat_id=1, date=d, out=False, sender_id=1, sender_name="", text="", html="")


class FolderTests(unittest.TestCase):
    def test_builtin(self):
        everything, archive = Folder(ALL_ID, "all"), Folder(ARCHIVE_ID, "arch")
        a, b = chat(1), chat(2, archived=True)
        self.assertTrue(everything.contains(a))
        self.assertFalse(everything.contains(b))
        self.assertTrue(archive.contains(b))
        self.assertFalse(everything.contains(chat(3, in_dialogs=False)))

    def test_filter_flags(self):
        f = folder_from_filter(t.DialogFilter(
            id=5, title=t.TextWithEntities("Work", []), pinned_peers=[], include_peers=[t.InputPeerUser(9, 0)],
            exclude_peers=[t.InputPeerChannel(7, 0)], groups=True, exclude_muted=True,
        ))
        self.assertEqual(f.title, "Work")
        self.assertTrue(f.contains(chat(9)))  # explicitly included user
        self.assertFalse(f.contains(chat(2)))  # other users are not
        self.assertTrue(f.contains(chat(-100, "group")))
        self.assertFalse(f.contains(chat(-101, "group", muted_until=int(time.time()) + 100)))
        self.assertFalse(f.contains(chat(-1000000000007, "group")))  # excluded channel id

    def test_ordering(self):
        f = Folder(ALL_ID, "all")
        older, newer = chat(1, last=msg(1, 60)), chat(2, last=msg(2, 1))
        pinned = chat(3, pinned=True, pin_rank=0, last=msg(3, 600))
        self.assertEqual([c.peer_id for c in sorted([older, newer, pinned], key=f.rank)], [3, 2, 1])


class TextTests(unittest.TestCase):
    def test_plural(self):
        words = ("участник", "участника", "участников")
        self.assertEqual([plural(n, *words) for n in (1, 2, 5, 11, 21, 22, 112)],
                         ["участник", "участника", "участников", "участников", "участник", "участника", "участников"])

    def test_presence(self):
        self.assertEqual(presence_text(t.UserStatusOnline(expires=datetime.now(timezone.utc))), "в сети")
        self.assertEqual(presence_text(t.UserStatusRecently()), "был(а) недавно")
        just = t.UserStatusOffline(was_online=datetime.now(timezone.utc) - timedelta(seconds=20))
        self.assertEqual(presence_text(just), "был(а) только что")
        self.assertEqual(presence_text(None), "был(а) давно")

    def test_dates(self):
        today = date(2026, 11, 3)
        self.assertEqual(day_title(today, today), "Сегодня")
        self.assertEqual(day_title(date(2026, 11, 2), today), "Вчера")
        self.assertEqual(day_title(date(2026, 5, 9), today), "9 мая")
        self.assertEqual(day_title(date(2025, 5, 9), today), "9 мая 2025")
        now = datetime(2026, 11, 3, 15, 0).astimezone()
        self.assertEqual(list_time(now - timedelta(hours=1), now), "14:00")
        self.assertEqual(list_time(now - timedelta(days=30), now), (now - timedelta(days=30)).strftime("%d.%m.%y"))

    def test_mute_until_accepts_datetime(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        self.assertAlmostEqual(mute_until(t.PeerNotifySettings(mute_until=future)), int(future.timestamp()))
        self.assertEqual(mute_until(t.PeerNotifySettings()), 0)

    def test_human_size(self):
        self.assertEqual(human_size(500), "500 Б")
        self.assertEqual(human_size(1536), "1.5 КБ")


if __name__ == "__main__":
    unittest.main()
