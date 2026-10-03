import itertools
import tempfile
import unittest
from pathlib import Path

from core import db
from utils import ctfs
from utils.ctf_places import Place, locate, without_bot_channel, wrong_place
from tests.test_ctfs import new_ctf, utc

_ids = itertools.count(1000)


class FakeChannel:
    """A text channel, in the category with category_id (None when it is in no category)."""
    def __init__(self, category_id, channel_id=None):
        self.id = next(_ids) if channel_id is None else channel_id
        self.category_id = category_id


class FakeThread:
    def __init__(self, parent):
        self.id, self.parent = next(_ids), parent
        self.category_id = parent.category_id


class FakeDm:
    def __init__(self):
        self.id = next(_ids)


class LocateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)
        self.ctf = ctfs.create(new_ctf(role_id=1, category_id=2, main_channel_id=3, bot_channel_id=4))
        self.main = FakeChannel(2, channel_id=3)
        self.bot = FakeChannel(2, channel_id=4)

    def test_main_channel(self):
        location = locate(self.main)

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.MAIN, None))

    def test_bot_channel(self):
        location = locate(self.bot)

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.BOT, None))

    def test_other_channel_in_the_ctf_category_is_a_category_channel(self):
        web = FakeChannel(2)

        location = locate(web)

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.CATEGORY, web))

    def test_thread_in_a_category_channel_is_a_challenge_thread_of_that_channel(self):
        web = FakeChannel(2)

        location = locate(FakeThread(web))

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.CHALLENGE, web))

    def test_thread_in_the_main_or_bot_channel_is_in_the_ctf_but_no_place_for_commands(self):
        for parent in (self.main, self.bot):
            location = locate(FakeThread(parent))

            self.assertEqual((location.ctf, location.place, location.category_channel),
                             (self.ctf, Place.ELSEWHERE, None))

    def test_channel_outside_a_ctf_category(self):
        for channel in (FakeChannel(99), FakeChannel(None), FakeThread(FakeChannel(99)), FakeDm()):
            location = locate(channel)

            self.assertEqual((location.ctf, location.place, location.category_channel), (None, Place.ELSEWHERE, None))

    def test_channels_of_a_removed_ctf_are_not_in_a_ctf(self):
        ctfs.mark_removed(self.ctf.id, utc(2026, 11, 1))

        self.assertEqual(locate(self.bot).place, Place.ELSEWHERE)
        self.assertIsNone(locate(self.bot).ctf)

    def test_found_by_ids_so_names_do_not_matter(self):
        # The fakes have no names at all: only the stored IDs are used
        other = ctfs.create(new_ctf(name="Bar CTF", role_id=11, category_id=12, main_channel_id=13,
                                    bot_channel_id=14))

        self.assertEqual(locate(FakeChannel(12, channel_id=14)).ctf, other)
        self.assertEqual(locate(self.bot).ctf, self.ctf)


class WithoutBotChannelTest(unittest.TestCase):
    def test_only_the_bot_channel_is_left_out(self):
        main, bot, web = FakeChannel(2, channel_id=3), FakeChannel(2, channel_id=4), FakeChannel(2)

        self.assertEqual(without_bot_channel(new_ctf(bot_channel_id=4), [main, bot, web]), [main, web])


class WrongPlaceTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)
        self.ctf = ctfs.create(new_ctf(role_id=1, category_id=2, main_channel_id=3, bot_channel_id=4))

    def test_allowed_place_is_not_wrong(self):
        self.assertIsNone(wrong_place(locate(FakeChannel(2, channel_id=4)), Place.BOT))
        self.assertIsNone(wrong_place(locate(FakeChannel(2)), Place.MAIN, Place.CATEGORY))

    def test_in_the_ctf_it_links_the_right_channel(self):
        self.assertEqual(wrong_place(locate(FakeChannel(2, channel_id=3)), Place.BOT),
                         "Run this in the #bot channel of the CTF: <#4>")
        self.assertEqual(wrong_place(locate(FakeChannel(2, channel_id=4)), Place.MAIN),
                         "Run this in the main channel of the CTF: <#3>")

    def test_outside_a_ctf_it_names_the_place(self):
        self.assertEqual(wrong_place(locate(FakeChannel(99)), Place.BOT), "Run this in the #bot channel of a CTF")
        self.assertEqual(wrong_place(locate(FakeChannel(99)), Place.MAIN), "Run this in the main channel of a CTF")

    def test_category_channels_and_threads_are_named(self):
        self.assertEqual(wrong_place(locate(FakeChannel(2, channel_id=4)), Place.CHALLENGE),
                         "Run this in a challenge thread of the CTF")
        self.assertEqual(wrong_place(locate(FakeChannel(99)), Place.CATEGORY, Place.CHALLENGE),
                         "Run this in a category channel or a challenge thread of a CTF")

    def test_several_places_are_listed(self):
        self.assertEqual(wrong_place(locate(FakeChannel(2, channel_id=4)), Place.MAIN, Place.CATEGORY, Place.CHALLENGE),
                         "Run this in the main channel, a category channel or a challenge thread of the CTF")


if __name__ == "__main__":
    unittest.main()
