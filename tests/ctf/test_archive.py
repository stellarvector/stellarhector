import asyncio
import os
import re
import unittest
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

import discord

# GitPython refuses to be imported without a git executable; the git work is faked here
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

from ctf import store
from ctf.archive import archive_ctf
from ctf.models import NewCtf
from tests.factories import use_temporary_database, utc
from tests.fakes import FakeArchivedChannel, FakeCategory, FakeGuild, fake_message

NOW = utc(2026, 10, 17, 8)


class FakeRepository:
    """Stands in for the archive repository (archive/repository.py): a checkout at path whose git work (syncing and
    saving) is recorded, or fails saving."""

    def __init__(self, path, save_error=None):
        self.path, self.save_error, self.calls = path, save_error, []
        self.lock = asyncio.Lock()

    async def sync(self):
        self.calls.append("sync")

    async def save(self, message, paths):
        self.calls.append("save")
        if self.save_error is not None:
            raise self.save_error


class ArchiveTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.archive_path = use_temporary_database(self).parent / "archive"
        self.archive_path.mkdir()
        (self.archive_path / "index.html").write_text("<ul><!--add-year--></ul>")
        (self.archive_path / "common").mkdir()
        for stylesheet in ("archive.css", "codehilite.css"):
            (self.archive_path / "common" / stylesheet).write_text("")
        self.git = FakeRepository(self.archive_path)

        self.guild = FakeGuild()
        self.guild.channel_ids = list(range(500, 510))
        self.category = FakeCategory({})
        self.main, self.bot_channel, self.web = (
            FakeArchivedChannel(self.guild, name, texts)
            for name, texts in (
                ("foo-ctf", ["gl hf"]),
                ("bot", ["staff only"]),
                ("web", ["🧩 `sqli`, started by @alice", "🧩 `xss`, started by @bob", "anyone seen the admin panel?"]),
            )
        )
        self.web.thread("sqli", ["sqli in /login"], on="🧩 `sqli`, started by @alice")
        self.web.thread("✅ xss", ["alert(1) works"], archived=True, on="🧩 `xss`, started by @bob")
        self.category.channels = [self.main, self.bot_channel, self.web]
        self.guild.channels = [self.category, *self.category.channels]

        self.ctf = store.create(
            NewCtf(
                name="Foo CTF",
                ctftime_id=None,
                start=None,
                finish=None,
                role_id=1,
                category_id=self.category.id,
                main_channel_id=self.main.id,
                bot_channel_id=self.bot_channel.id,
                guide_message_id=2,
            )
        )

    async def archive(self):
        await archive_ctf(self.guild, self.ctf, NOW, self.git, ZoneInfo("Europe/Brussels"))

    def pages(self, ctf_folder="Foo-CTF"):
        """The pages of the CTF's archive, by their path in its folder."""
        folder = next(self.archive_path.glob(f"*/{ctf_folder}"))
        return {page.relative_to(folder).as_posix(): page.read_text() for page in folder.glob("**/*.html")}

    async def test_each_challenge_thread_gets_a_page_under_its_category(self):
        await self.archive()

        pages = self.pages()
        self.assertEqual(set(pages), {"foo-ctf.html", "web/index.html", "web/sqli.html", "web/xss.html"})
        self.assertIn("sqli in /login", pages["web/sqli.html"])
        self.assertIn("alert(1) works", pages["web/xss.html"])
        self.assertIn("gl hf", pages["foo-ctf.html"])

    async def test_the_category_page_has_the_messages_in_the_channel_with_links_to_its_challenges(self):
        await self.archive()

        # Leaving out the navigation, which links every page too
        page = self.pages()["web/index.html"].split('id="content"')[1]
        self.assertIn("anyone seen the admin panel?", page)
        self.assertLess(page.index("started by @alice"), page.index('href="sqli.html"'))
        self.assertLess(page.index('href="sqli.html"'), page.index("started by @bob"))
        self.assertLess(page.index("started by @bob"), page.index('href="xss.html"'))
        self.assertNotIn("sqli in /login", page)

    async def test_every_link_and_stylesheet_of_every_page_exists(self):
        await self.archive()

        folder = next(self.archive_path.glob("*/Foo-CTF"))
        for path, page in self.pages().items():
            links = re.findall(r'href="([^"#]+)"', page)
            self.assertIn("../index.html" if "/" not in path else "../../index.html", links)
            for link in links:
                with self.subTest(page=path, link=link):
                    self.assertTrue((folder / path).parent.joinpath(link).resolve().is_file())

    async def test_every_page_links_every_page_in_the_navigation(self):
        await self.archive()

        self.assertIn('href="web/xss.html"', self.pages()["foo-ctf.html"])
        self.assertIn('href="../foo-ctf.html"', self.pages()["web/sqli.html"])
        self.assertIn('href="index.html"', self.pages()["web/sqli.html"])
        self.assertIn('href="xss.html"', self.pages()["web/sqli.html"])

    async def test_the_year_index_links_the_main_channel_page(self):
        await self.archive()

        year_index = next(self.archive_path.glob("*/index.html")).read_text()
        self.assertIn('href="./Foo-CTF/foo-ctf.html"', year_index)

    async def test_the_bot_channel_is_not_archived(self):
        self.bot_channel.thread("approvals", ["approve bob?"])

        await self.archive()

        pages = "".join(self.pages().values())
        self.assertNotIn("staff only", pages)
        self.assertNotIn("approve bob?", pages)

    async def test_threads_made_by_hand_get_a_page_too(self):
        self.web.thread("no starter", ["first message"])
        self.web.thread("secret", ["private notes"], archived=True, private=True)

        await self.archive()

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

        await self.archive()

        page = self.pages()["web/index.html"].split('id="content"')[1]
        self.assertLess(page.index('href="forensics.html"'), page.index("started by @alice"))

    async def test_a_thread_both_active_and_archived_gets_one_page(self):
        thread = self.web.thread("rev", ["strings ftw"])
        self.web.archived[False].append(thread)

        await self.archive()

        self.assertEqual([path for path in self.pages() if "rev" in path], ["web/rev.html"])

    async def test_threads_with_the_same_page_name_get_numbered_and_none_is_named_like_the_category_page(self):
        self.web.thread("sqli", ["second try"])
        self.web.thread("index", ["about the index"])

        await self.archive()

        pages = self.pages()
        self.assertIn("sqli in /login", pages["web/sqli.html"])
        self.assertIn("second try", pages["web/sqli-2.html"])
        self.assertIn("about the index", pages["web/index-2.html"])
        self.assertIn("anyone seen the admin panel?", pages["web/index.html"])

    async def test_a_channel_made_by_hand_is_archived_like_a_category(self):
        notes = FakeArchivedChannel(self.guild, "📝 notes", ["useful links"])
        notes.thread("tools", ["ghidra"])
        self.category.channels.append(notes)

        await self.archive()

        pages = self.pages()
        self.assertIn("useful links", pages["notes/index.html"])
        self.assertIn("ghidra", pages["notes/tools.html"])

    async def test_a_channel_without_messages_of_its_own_is_left_out(self):
        # As a forum or voice channel: no history, or no threads
        self.category.channels += [
            SimpleNamespace(id=self.guild.channel_ids.pop(0), name="forum", threads=[]),
            SimpleNamespace(id=self.guild.channel_ids.pop(0), name="voice"),
        ]
        self.category.channels[-2].archived_threads = self.web.archived_threads

        await self.archive()

        self.assertFalse(any(path.startswith(("forum/", "voice/")) for path in self.pages()))

    async def test_an_older_archive_of_the_ctf_is_left_as_it_is(self):
        old = self.archive_path / str(datetime.now().year) / "Foo-CTF"
        old.mkdir(parents=True)
        (old / "web.html").write_text("old layout")
        (self.archive_path / str(datetime.now().year) / "index.html").write_text("<ul><!--add-ctf--></ul>")

        await self.archive()

        self.assertEqual(self.pages(), {"web.html": "old layout"})
        self.assertIn("web/sqli.html", self.pages("Foo-CTF-2"))

    async def test_the_archive_repository_is_synced_then_saved_and_the_archive_time_recorded(self):
        await self.archive()

        self.assertEqual(self.git.calls, ["sync", "save"])
        self.assertEqual(store.get(self.ctf.id).archived_at, NOW)

    async def test_a_failing_save_is_raised_and_no_archive_time_recorded(self):
        self.git.save_error = RuntimeError("push rejected")

        with self.assertRaisesRegex(RuntimeError, "push rejected"):
            await self.archive()

        self.assertIsNone(store.get(self.ctf.id).archived_at)

    async def test_a_failing_save_leaves_nothing_behind_so_a_new_try_starts_afresh(self):
        index = (self.archive_path / "index.html").read_text()
        self.git.save_error = RuntimeError("push rejected")
        with self.assertRaises(RuntimeError):
            await self.archive()

        self.assertEqual(list(self.archive_path.glob("*/Foo-CTF*")), [])
        self.assertEqual((self.archive_path / "index.html").read_text(), index)

        self.git.save_error = None
        await self.archive()

        self.assertIn("web/sqli.html", self.pages())
        year_index = next(self.archive_path.glob("*/index.html")).read_text()
        self.assertEqual(year_index.count('href="./Foo-CTF/'), 1)

    async def test_a_failing_download_leaves_the_year_index_as_it_was(self):
        year = self.archive_path / str(datetime.now().year)
        year.mkdir()
        (year / "index.html").write_text("<ul><!--add-ctf--></ul>")
        self.web.messages[0].attachments = [
            SimpleNamespace(id=7, filename="chall.zip", url="https://example.com/chall.zip")
        ]

        with mock.patch("archive.message._download", side_effect=OSError("expired")):
            with self.assertRaisesRegex(OSError, "expired"):
                await self.archive()

        self.assertEqual(list(year.glob("Foo-CTF*")), [])
        self.assertEqual((year / "index.html").read_text(), "<ul><!--add-ctf--></ul>")
        self.assertEqual(self.git.calls, ["sync"])
        self.assertIsNone(store.get(self.ctf.id).archived_at)

    async def test_a_ctf_name_that_is_no_safe_path_stays_inside_the_year_folder(self):
        self.ctf = replace(self.ctf, name="../../etc/Foo CTF")

        await self.archive()

        year = self.archive_path / str(datetime.now().year)
        self.assertEqual([folder.name for folder in year.iterdir() if folder.is_dir()], ["etcFoo-CTF"])
        self.assertIn('href="./etcFoo-CTF/foo-ctf.html"', (year / "index.html").read_text())

    async def test_attachments_are_saved_under_a_safe_name_the_page_links_to(self):
        self.main.messages[0].attachments = [
            SimpleNamespace(id=7, filename="../../evil name.png", url="https://example.com/a.png")
        ]
        saved = []

        with mock.patch("archive.message._download", side_effect=lambda url, path: saved.append(path)):
            await self.archive()

        folder = next(self.archive_path.glob("*/Foo-CTF"))
        self.assertEqual(saved, [folder / "attachments" / "7__.._evil_name.png"])
        self.assertIn('src="./attachments/7__.._evil_name.png"', self.pages()["foo-ctf.html"])

    async def test_without_its_category_only_the_main_channel_is_archived(self):
        self.guild.channels.remove(self.category)

        await self.archive()

        self.assertEqual(set(self.pages()), {"foo-ctf.html"})


if __name__ == "__main__":
    unittest.main()
