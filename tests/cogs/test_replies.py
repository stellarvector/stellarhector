import asyncio
import unittest
from datetime import timedelta
from types import SimpleNamespace

from cogs.replies import run_now, wrong_place
from ctf import store
from ctf.location import Place, locate
from feeds import FeedError
from tests.factories import new_ctf, use_temporary_database
from tests.fakes import LocatedChannel


class WrongPlaceTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf(role_id=1, category_id=2, main_channel_id=3, bot_channel_id=4))

    def test_allowed_place_is_not_wrong(self):
        self.assertIsNone(wrong_place(locate(LocatedChannel(2, channel_id=4)), Place.BOT))
        self.assertIsNone(wrong_place(locate(LocatedChannel(2)), Place.MAIN, Place.CATEGORY))

    def test_in_the_ctf_it_links_the_right_channel(self):
        self.assertEqual(
            wrong_place(locate(LocatedChannel(2, channel_id=3)), Place.BOT),
            "Run this in the #bot channel of the CTF: <#4>",
        )
        self.assertEqual(
            wrong_place(locate(LocatedChannel(2, channel_id=4)), Place.MAIN),
            "Run this in the main channel of the CTF: <#3>",
        )

    def test_outside_a_ctf_it_names_the_place(self):
        self.assertEqual(wrong_place(locate(LocatedChannel(99)), Place.BOT), "Run this in the #bot channel of a CTF")
        self.assertEqual(wrong_place(locate(LocatedChannel(99)), Place.MAIN), "Run this in the main channel of a CTF")

    def test_category_channels_and_threads_are_named(self):
        self.assertEqual(
            wrong_place(locate(LocatedChannel(2, channel_id=4)), Place.CHALLENGE),
            "Run this in a challenge thread of the CTF",
        )
        self.assertEqual(
            wrong_place(locate(LocatedChannel(99)), Place.CATEGORY, Place.CHALLENGE),
            "Run this in a category channel or a challenge thread of a CTF",
        )

    def test_several_places_are_listed(self):
        self.assertEqual(
            wrong_place(locate(LocatedChannel(2, channel_id=4)), Place.MAIN, Place.CATEGORY, Place.CHALLENGE),
            "Run this in the main channel, a category channel or a challenge thread of the CTF",
        )


class RunNowTest(unittest.IsolatedAsyncioTestCase):
    """/blog-check, /calendar-sync and /ctftime-check run their job's work right away through run_now."""

    def setUp(self):
        self.edits = []

        async def defer(**kwargs):
            self.deferred = kwargs

        async def edit_original_response(content):
            self.edits.append(content)

        self.interaction = SimpleNamespace(
            response=SimpleNamespace(defer=defer), edit_original_response=edit_original_response
        )

    async def test_the_result_is_returned_for_the_command_to_reply_with(self):
        async def work():
            return 42

        self.assertEqual(await run_now(self.interaction, work(), timedelta(seconds=1), "blog check"), 42)
        self.assertEqual(self.deferred, {"thinking": True, "ephemeral": True})
        self.assertEqual(self.edits, [])

    async def test_an_unreadable_feed_is_reported_as_skipped(self):
        async def work():
            raise FeedError("Blog feed is `not` valid XML")

        self.assertIsNone(await run_now(self.interaction, work(), timedelta(seconds=1), "blog check"))
        self.assertEqual(
            self.edits, [":warning: The blog check was skipped, nothing changed: `Blog feed is 'not' valid XML`"]
        )

    async def test_work_that_takes_too_long_is_stopped(self):
        async def work():
            await asyncio.sleep(10)

        with self.assertLogs("bot", level="ERROR"):
            result = await run_now(self.interaction, work(), timedelta(milliseconds=10), "calendar sync")

        self.assertIsNone(result)
        self.assertEqual(
            self.edits,
            [":warning: The calendar sync took too long and was stopped. The next one carries on where it left off."],
        )


if __name__ == "__main__":
    unittest.main()
