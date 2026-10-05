import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# GitPython refuses to be imported without a git executable; nothing here runs git
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

from archive.channel import ChannelArchive, is_archived
from tests.fakes import FakeArchivedChannel

ZONE = ZoneInfo("Europe/Brussels")


class FakeGuild:
    def __init__(self):
        self.channel_ids = list(range(700, 720))


def channel(name, texts, category="General Stuff"):
    """A text channel as /archive-channel reads it, in the Discord category named category (None for none)."""
    archived = FakeArchivedChannel(FakeGuild(), name, texts)
    archived.category = None if category is None else SimpleNamespace(name=category)
    return archived


class ChannelArchiveTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "index.html").write_text("<ul><!--add-year--></ul>")

    async def archive(self, archived, overwrite=False):
        archive = await ChannelArchive.load(archived, self.root, ZONE)
        archive.generate_files(overwrite)
        return archive

    def page(self, category, name):
        return (self.root / "channels" / category / name / f"{name}.html").read_text()

    def channels_index(self):
        return (self.root / "channels" / "index.html").read_text()

    async def test_the_page_has_the_messages_with_their_threads_inline(self):
        general = channel("📢 general", ["hello", "plans for friday"])
        general.thread("friday", ["pizza?", "yes"], on="plans for friday")

        archive = await self.archive(general)

        self.assertEqual((archive.category, archive.archive_name), ("General-Stuff", "general"))
        page = self.page("General-Stuff", "general")
        self.assertLess(page.index("plans for friday"), page.index("pizza?"))
        self.assertIn("hello", page)

    async def test_the_first_archive_adds_the_channels_index_to_the_archive_index(self):
        await self.archive(channel("general", ["hello"]))

        self.assertIn('href="./channels/index.html"', (self.root / "index.html").read_text())
        self.assertIn('href="./General-Stuff/general/general.html"', self.channels_index())

    async def test_a_channel_without_category_goes_in_uncategorized(self):
        archive = await self.archive(channel("general", ["hello"], category=None))

        self.assertEqual(archive.category, "uncategorized")
        self.assertTrue(is_archived(self.root, "uncategorized", "general"))

    async def test_keeping_both_numbers_the_new_archive(self):
        await self.archive(channel("general", ["old"]))

        archive = await self.archive(channel("general", ["new"]))

        self.assertEqual(archive.archive_name, "general-2")
        self.assertIn("old", self.page("General-Stuff", "general"))
        self.assertIn("new", self.page("General-Stuff", "general-2"))
        self.assertIn('href="./General-Stuff/general-2/general-2.html"', self.channels_index())

    async def test_overwriting_replaces_the_archive_and_links_it_once(self):
        await self.archive(channel("general", ["old"]))
        (self.root / "channels" / "General-Stuff" / "general" / "attachments" / "stale.png").write_text("")

        archive = await self.archive(channel("general", ["new"]), overwrite=True)

        self.assertEqual(archive.archive_name, "general")
        self.assertIn("new", self.page("General-Stuff", "general"))
        self.assertNotIn(">old<", self.page("General-Stuff", "general"))
        self.assertFalse((self.root / "channels" / "General-Stuff" / "general" / "attachments" / "stale.png").exists())
        self.assertEqual(self.channels_index().count("general.html"), 1)

    async def test_the_commit_message_names_the_archive(self):
        archive = await self.archive(channel("general", ["hello"]))

        self.assertEqual(archive.commit_message, "Archive channel General-Stuff/general")


if __name__ == "__main__":
    unittest.main()
