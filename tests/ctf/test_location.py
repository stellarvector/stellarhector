import itertools
import unittest
from types import SimpleNamespace

from ctf import store
from ctf.location import Place, is_player_or_staff, locate, without_bot_channel
from tests.factories import ROLES, new_ctf, use_temporary_database, utc
from tests.fakes import LocatedChannel, LocatedThread

_ids = itertools.count(1000)


class FakeDm:
    id = 99999


class LocateTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf(role_id=1, category_id=2, main_channel_id=3, bot_channel_id=4))
        self.main = LocatedChannel(2, channel_id=3)
        self.bot = LocatedChannel(2, channel_id=4)

    def test_main_channel(self):
        location = locate(self.main)

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.MAIN, None))

    def test_bot_channel(self):
        location = locate(self.bot)

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.BOT, None))

    def test_other_channel_in_the_ctf_category_is_a_category_channel(self):
        web = LocatedChannel(2)

        location = locate(web)

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.CATEGORY, web))

    def test_thread_in_a_category_channel_is_a_challenge_thread_of_that_channel(self):
        web = LocatedChannel(2)

        location = locate(LocatedThread(web))

        self.assertEqual((location.ctf, location.place, location.category_channel), (self.ctf, Place.CHALLENGE, web))

    def test_thread_in_the_main_or_bot_channel_is_in_the_ctf_but_no_place_for_commands(self):
        for parent in (self.main, self.bot):
            location = locate(LocatedThread(parent))

            self.assertEqual(
                (location.ctf, location.place, location.category_channel), (self.ctf, Place.ELSEWHERE, None)
            )

    def test_channel_outside_a_ctf_category(self):
        for channel in (LocatedChannel(99), LocatedChannel(None), LocatedThread(LocatedChannel(99)), FakeDm()):
            location = locate(channel)

            self.assertEqual((location.ctf, location.place, location.category_channel), (None, Place.ELSEWHERE, None))

    def test_channels_of_a_removed_ctf_are_not_in_a_ctf(self):
        store.mark_removed(self.ctf.id, utc(2026, 11, 1))

        self.assertEqual(locate(self.bot).place, Place.ELSEWHERE)
        self.assertIsNone(locate(self.bot).ctf)

    def test_found_by_ids_so_names_do_not_matter(self):
        # The fakes have no names at all: only the stored IDs are used
        other = store.create(new_ctf(name="Bar CTF", role_id=11, category_id=12, main_channel_id=13, bot_channel_id=14))

        self.assertEqual(locate(LocatedChannel(12, channel_id=14)).ctf, other)
        self.assertEqual(locate(self.bot).ctf, self.ctf)


class WithoutBotChannelTest(unittest.TestCase):
    def test_only_the_bot_channel_is_left_out(self):
        main, bot, web = LocatedChannel(2, channel_id=3), LocatedChannel(2, channel_id=4), LocatedChannel(2)

        self.assertEqual(without_bot_channel(new_ctf(bot_channel_id=4), [main, bot, web]), [main, web])


def role(name):
    return SimpleNamespace(id=next(_ids), name=name)


def member(*roles):
    return SimpleNamespace(roles=list(roles))


class IsPlayerOrStaffTest(unittest.TestCase):
    def setUp(self):
        self.ctf_role = role("⚡ Foo CTF")
        self.ctf = new_ctf(role_id=self.ctf_role.id)

    def test_players_of_the_ctf_are(self):
        self.assertTrue(is_player_or_staff(member(role("sv{follower}"), self.ctf_role), self.ctf, ROLES.staff))

    def test_staff_are(self):
        for name in ROLES.staff:
            with self.subTest(name):
                self.assertTrue(is_player_or_staff(member(role(name)), self.ctf, ROLES.staff))

    def test_others_are_not(self):
        other_ctf_role = role("⚡ Bar CTF")

        self.assertFalse(is_player_or_staff(member(role("sv{follower}"), other_ctf_role), self.ctf, ROLES.staff))


if __name__ == "__main__":
    unittest.main()
