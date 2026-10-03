import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock

from jinja2 import Environment, PackageLoader, select_autoescape

import core


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


class FakeArchivedChannel:
    """A channel in the CTF's category with one message, as the archiver reads it."""
    def __init__(self, guild, name, text):
        self.id, self.name = guild.channel_ids.pop(), name
        author = SimpleNamespace(display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
                                 display_name="alice", name="alice", color="#ffffff", bot=False)
        self.messages = [SimpleNamespace(
            id=1, author=author, created_at=utc(2026, 10, 15, 12), edited_at=None, content=text, clean_content=text,
            system_content=text, attachments=[], interaction=None, reference=None, pinned=False, stickers=[],
            reactions=[])]
        self.threads = []

    async def history(self, limit=100, oldest_first=False):
        for message in self.messages:
            yield message

    async def archived_threads(self, private=False, limit=100):
        return
        yield


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
        self.main, self.bot_channel, self.web = (FakeArchivedChannel(self.guild, name, text) for name, text in (
            ("foo-ctf", "gl hf"), ("bot", "staff only"), ("web", "sqli in /login")))
        self.category.channels = [self.main, self.bot_channel, self.web]
        self.guild.channels = [self.category, *self.category.channels]

        self.ctf = ctfs.create(ctfs.NewCtf(
            name="Foo CTF", ctftime_id=None, start=None, finish=None, role_id=1, category_id=self.category.id,
            main_channel_id=self.main.id, bot_channel_id=self.bot_channel.id, guide_message_id=2))

    def pages(self):
        return {page.name: page.read_text() for page in self.archive_path.glob("*/Foo CTF/*.html")}

    async def test_each_channel_but_bot_gets_a_page_in_the_archive(self):
        await ctf_archive.archive(self.guild, self.ctf, NOW)

        pages = self.pages()
        self.assertEqual(set(pages), {"foo-ctf.html", "web.html"})
        self.assertIn("sqli in /login", pages["web.html"])
        self.assertNotIn("staff only", "".join(pages.values()))

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
