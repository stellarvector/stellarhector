import itertools
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

from jinja2 import Environment, PackageLoader, select_autoescape

import core
import discord


def _stand_in_bot():
    """What the archiver uses of core.bot, which can't be imported without the bot's .env (GUILD_ID)."""
    bot = ModuleType("core.bot")
    bot.config, bot.TIMEZONE = {}, "Europe/Brussels"
    bot.jinja_env = Environment(loader=PackageLoader("utils", "templates"), autoescape=select_autoescape())
    return bot


if "core.bot" not in sys.modules:
    sys.modules["core.bot"] = core.bot = _stand_in_bot()
# GitPython refuses to be imported without a git executable; the git work is faked here
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

import core.bot as bot
from core import db
from tests.test_ctf_approval import FakeGuild, utc
from tests.test_ctf_release import FakeCategory
from utils import ctf_archive, ctfs
from utils.archive.ctf import CtfArchive

NOW = utc(2026, 10, 17, 8)


_ids = itertools.count(1000)


def fake_message(text, type=discord.MessageType.default):
    """A message as the archiver reads it."""
    author = SimpleNamespace(display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
                             display_name="alice", name="alice", color="#ffffff", bot=False)
    return SimpleNamespace(
        id=next(_ids), type=type, author=author, created_at=utc(2026, 10, 15, 12), edited_at=None, content=text,
        clean_content=text, system_content=text, attachments=[], interaction=None, reference=None, pinned=False,
        stickers=[], reactions=[])


class FakeHistory:
    """Something with messages, as the archiver reads it: a channel or a thread."""
    def __init__(self, id, name, texts):
        self.id, self.name = id, name
        self.messages = [fake_message(text) for text in texts]

    async def history(self, limit=100, oldest_first=False):
        for message in self.messages:
            yield message


class FakeArchivedChannel(FakeHistory):
    """A channel in the CTF's category with its messages, and its active and archived threads."""
    def __init__(self, guild, name, texts):
        super().__init__(guild.channel_ids.pop(0), name, texts)
        self.threads, self.archived = [], {False: [], True: []}

    def thread(self, name, texts, archived=False, private=False, on=None):
        """A thread named name with the texts as its messages, made on the message with the text on (or on none).

        As Discord does: a thread made on a message has that message's ID, and starts with a reference to it."""
        if on is None:
            thread = FakeHistory(next(_ids), name, texts)
        else:
            starter = next(message for message in self.messages if message.content == on)
            thread = FakeHistory(starter.id, name, texts)
            thread.messages.insert(0, fake_message("", type=discord.MessageType.thread_starter_message))
        (self.archived[private] if archived else self.threads).append(thread)
        return thread

    async def archived_threads(self, private=False, limit=100):
        for thread in self.archived[private]:
            yield thread


class FakeGit:
    """Stands in for the git work of the archiver (syncing and committing the archive repository): records it, or
    fails saving."""
    def __init__(self, save_error=None):
        self.save_error, self.calls = save_error, []

    async def sync_repository(self):
        self.calls.append("sync")

    async def save(self, archive):
        self.calls.append("save")
        if self.save_error is not None:
            raise self.save_error


class ArchiveTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)

        self.archive_path = Path(tmp.name) / "archive"
        self.archive_path.mkdir()
        (self.archive_path / "index.html").write_text("<ul><!--add-year--></ul>")
        (self.archive_path / "common").mkdir()
        for stylesheet in ("archive.css", "codehilite.css"):
            (self.archive_path / "common" / stylesheet).write_text("")
        config = mock.patch.dict(bot.config, {"ARCHIVE_LOCAL_PATH": str(self.archive_path)})
        config.start()
        self.addCleanup(config.stop)

        self.git = FakeGit()
        for patch in (mock.patch.object(CtfArchive, "sync_repository", self.git.sync_repository),
                      mock.patch.object(CtfArchive, "save", lambda archive: self.git.save(archive))):
            patch.start()
            self.addCleanup(patch.stop)

        self.guild = FakeGuild()
        self.guild.channel_ids = list(range(500, 510))
        self.category = FakeCategory({})
        self.main, self.bot_channel, self.web = (FakeArchivedChannel(self.guild, name, texts) for name, texts in (
            ("foo-ctf", ["gl hf"]), ("bot", ["staff only"]),
            ("web", ["🧩 `sqli`, started by @alice", "🧩 `xss`, started by @bob", "anyone seen the admin panel?"])))
        self.web.thread("sqli", ["sqli in /login"], on="🧩 `sqli`, started by @alice")
        self.web.thread("✅ xss", ["alert(1) works"], archived=True, on="🧩 `xss`, started by @bob")
        self.category.channels = [self.main, self.bot_channel, self.web]
        self.guild.channels = [self.category, *self.category.channels]

        self.ctf = ctfs.create(ctfs.NewCtf(
            name="Foo CTF", ctftime_id=None, start=None, finish=None, role_id=1, category_id=self.category.id,
            main_channel_id=self.main.id, bot_channel_id=self.bot_channel.id, guide_message_id=2))

    def pages(self, ctf_folder="Foo CTF"):
        """The pages of the CTF's archive, by their path in its folder."""
        folder = next(self.archive_path.glob(f"*/{ctf_folder}"))
        return {page.relative_to(folder).as_posix(): page.read_text() for page in folder.glob("**/*.html")}

    async def test_each_challenge_thread_gets_a_page_under_its_category(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        pages = self.pages()
        self.assertEqual(set(pages), {"foo-ctf.html", "web/index.html", "web/sqli.html", "web/xss.html"})
        self.assertIn("sqli in /login", pages["web/sqli.html"])
        self.assertIn("alert(1) works", pages["web/xss.html"])
        self.assertIn("gl hf", pages["foo-ctf.html"])

    async def test_the_category_page_has_the_messages_in_the_channel_with_links_to_its_challenges(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        # Leaving out the navigation, which links every page too
        page = self.pages()["web/index.html"].split('id="content"')[1]
        self.assertIn("anyone seen the admin panel?", page)
        self.assertLess(page.index("started by @alice"), page.index('href="sqli.html"'))
        self.assertLess(page.index('href="sqli.html"'), page.index("started by @bob"))
        self.assertLess(page.index("started by @bob"), page.index('href="xss.html"'))
        self.assertNotIn("sqli in /login", page)

    async def test_every_link_and_stylesheet_of_every_page_exists(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        folder = next(self.archive_path.glob("*/Foo CTF"))
        for path, page in self.pages().items():
            links = re.findall(r'href="([^"#]+)"', page)
            self.assertIn("../index.html" if "/" not in path else "../../index.html", links)
            for link in links:
                with self.subTest(page=path, link=link):
                    self.assertTrue((folder / path).parent.joinpath(link).resolve().is_file())

    async def test_every_page_links_every_page_in_the_navigation(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        self.assertIn('href="web/xss.html"', self.pages()["foo-ctf.html"])
        self.assertIn('href="../foo-ctf.html"', self.pages()["web/sqli.html"])
        self.assertIn('href="index.html"', self.pages()["web/sqli.html"])
        self.assertIn('href="xss.html"', self.pages()["web/sqli.html"])

    async def test_the_year_index_links_the_main_channel_page(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        year_index = next(self.archive_path.glob("*/index.html")).read_text()
        self.assertIn('href="./Foo CTF/foo-ctf.html"', year_index)

    async def test_the_bot_channel_is_not_archived(self):
        self.bot_channel.thread("approvals", ["approve bob?"])

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        pages = "".join(self.pages().values())
        self.assertNotIn("staff only", pages)
        self.assertNotIn("approve bob?", pages)

    async def test_threads_made_by_hand_get_a_page_too(self):
        self.web.thread("no starter", ["first message"])
        self.web.thread("secret", ["private notes"], archived=True, private=True)

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        pages = self.pages()
        # Discord leaves no reference in a thread made on no message: its first message is the thread's own
        self.assertIn("first message", pages["web/no-starter.html"])
        self.assertIn("private notes", pages["web/secret.html"])
        self.assertIn('href="no-starter.html"', pages["web/index.html"].split('id="content"')[1])

    async def test_a_thread_made_with_the_button_is_linked_where_discord_says_it_was_made(self):
        thread = self.web.thread("forensics", ["pcap attached"])
        created = fake_message("alice started a thread", type=discord.MessageType.thread_created)
        created.reference = SimpleNamespace(message_id=None, channel_id=thread.id)
        self.web.messages.insert(0, created)

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        page = self.pages()["web/index.html"].split('id="content"')[1]
        self.assertLess(page.index('href="forensics.html"'), page.index("started by @alice"))

    async def test_a_thread_both_active_and_archived_gets_one_page(self):
        thread = self.web.thread("rev", ["strings ftw"])
        self.web.archived[False].append(thread)

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        self.assertEqual([path for path in self.pages() if "rev" in path], ["web/rev.html"])

    async def test_threads_with_the_same_page_name_get_numbered_and_none_is_named_like_the_category_page(self):
        self.web.thread("sqli", ["second try"])
        self.web.thread("index", ["about the index"])

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        pages = self.pages()
        self.assertIn("sqli in /login", pages["web/sqli.html"])
        self.assertIn("second try", pages["web/sqli-2.html"])
        self.assertIn("about the index", pages["web/index-2.html"])
        self.assertIn("anyone seen the admin panel?", pages["web/index.html"])

    async def test_a_channel_made_by_hand_is_archived_like_a_category(self):
        notes = FakeArchivedChannel(self.guild, "📝 notes", ["useful links"])
        notes.thread("tools", ["ghidra"])
        self.category.channels.append(notes)

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        pages = self.pages()
        self.assertIn("useful links", pages["notes/index.html"])
        self.assertIn("ghidra", pages["notes/tools.html"])

    async def test_a_channel_without_messages_of_its_own_is_left_out(self):
        # As a forum or voice channel: no history, or no threads
        self.category.channels += [SimpleNamespace(id=self.guild.channel_ids.pop(0), name="forum", threads=[]),
                                   SimpleNamespace(id=self.guild.channel_ids.pop(0), name="voice")]
        self.category.channels[-2].archived_threads = self.web.archived_threads

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        self.assertFalse(any(path.startswith(("forum/", "voice/")) for path in self.pages()))

    async def test_an_older_archive_of_the_ctf_is_left_as_it_is(self):
        old = self.archive_path / str(datetime.now().year) / "Foo CTF"
        old.mkdir(parents=True)
        (old / "web.html").write_text("old layout")
        (self.archive_path / str(datetime.now().year) / "index.html").write_text("<ul><!--add-ctf--></ul>")

        await ctf_archive.archive(self.guild, self.ctf, NOW)

        self.assertEqual(self.pages(), {"web.html": "old layout"})
        self.assertIn("web/sqli.html", self.pages("Foo CTF-1"))

    async def test_the_archive_repository_is_synced_then_saved_and_the_archive_time_recorded(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        self.assertEqual(self.git.calls, ["sync", "save"])
        self.assertEqual(ctfs.get(self.ctf.id).archived_at, NOW)

    async def test_a_failing_save_is_raised_and_no_archive_time_recorded(self):
        self.git.save_error = RuntimeError("push rejected")

        with self.assertRaisesRegex(RuntimeError, "push rejected"):
            await ctf_archive.archive(self.guild, self.ctf, NOW)

        self.assertIsNone(ctfs.get(self.ctf.id).archived_at)


if __name__ == "__main__":
    unittest.main()
