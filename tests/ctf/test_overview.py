import itertools
import unittest

from ctf import overview, store
from ctf.models import Category, Challenge
from tests.factories import new_ctf, use_temporary_database
from tests.fakes import PinningChannel

_ids = itertools.count(5000)


class TextTest(unittest.TestCase):
    def test_challenges_are_grouped_under_their_category_channel(self):
        categories = [Category("crypto", 20), Category("web", 21)]
        challenges = [
            Challenge("crypto", "rsa", 30, solved=True),
            Challenge("web", "sqli", 31, solved=False),
            Challenge("web", "xss", 32, solved=False),
        ]

        self.assertEqual(overview.text(categories, challenges), "**Challenges**\n\n<#20>\n<#30>\n\n<#21>\n<#31>\n<#32>")

    def test_categories_without_challenges_are_left_out(self):
        categories = [Category("crypto", 20), Category("web", 21)]

        self.assertEqual(
            overview.text(categories, [Challenge("web", "xss", 32, solved=False)]), "**Challenges**\n\n<#21>\n<#32>"
        )

    def test_a_category_not_stored_is_named_by_its_slug(self):
        self.assertEqual(
            overview.text([], [Challenge("web", "xss", 32, solved=False)]), "**Challenges**\n\n**web**\n<#32>"
        )

    def test_everything_is_shown_when_it_fits_the_limit_exactly(self):
        challenges = [Challenge("web", "xss", 32, solved=False)]
        full = overview.text([Category("web", 21)], challenges)

        self.assertEqual(overview.text([Category("web", 21)], challenges, limit=len(full)), full)

    def test_a_long_overview_is_cut_and_says_how_many_are_left_out(self):
        categories = [Category("crypto", 20), Category("web", 21)]
        challenges = [
            Challenge("crypto", "a", 30, solved=False),
            Challenge("crypto", "b", 31, solved=False),
            Challenge("web", "c", 32, solved=False),
        ]
        # Room for the title, crypto and its first challenge, and the line saying the rest is left out
        limit = len("**Challenges**\n\n<#20>\n<#30>\n\n… and 2 more")

        self.assertEqual(
            overview.text(categories, challenges, limit=limit), "**Challenges**\n\n<#20>\n<#30>\n\n… and 2 more"
        )

    def test_a_category_header_is_not_shown_without_any_of_its_challenges(self):
        categories = [Category("crypto", 20), Category("web", 21)]
        challenges = [
            Challenge("crypto", "a", 30, solved=False),
            Challenge("web", "b", 31, solved=False),
            Challenge("web", "c", 32, solved=False),
        ]
        # Room for the web header, but not for its first challenge too
        limit = len("**Challenges**\n\n<#20>\n<#30>\n\n<#21>\n\n… and 2 more")

        self.assertEqual(
            overview.text(categories, challenges, limit=limit), "**Challenges**\n\n<#20>\n<#30>\n\n… and 2 more"
        )

    def test_many_challenges_stay_within_discords_message_limit(self):
        categories = [Category(f"cat{c}", 10**18 + c) for c in range(5)]
        challenges = [
            Challenge(f"cat{c}", f"chal{i:03}", 10**18 + 100 * c + i, solved=i % 2 == 0)
            for c in range(5)
            for i in range(30)
        ]

        text = overview.text(categories, challenges)

        self.assertLessEqual(len(text), 2000)
        shown = text.count("<#") - text.count("\n\n<#")
        self.assertTrue(text.endswith(f"… and {150 - shown} more"))


class FakeGuild:
    def __init__(self, *channels):
        self.channels = list(channels)

    def get_channel(self, channel_id):
        return next((channel for channel in self.channels if channel.id == channel_id), None)


class UpdateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.main = PinningChannel(3)
        self.guild = FakeGuild(self.main)
        self.ctf = store.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        store.add_category(self.ctf.id, "web", 21)

    async def test_nothing_is_posted_before_the_first_challenge(self):
        await overview.update(self.guild, self.ctf.id)

        self.assertEqual(self.main.messages, [])

    async def test_the_first_update_posts_and_pins_the_overview_in_the_main_channel(self):
        store.add_challenge(self.ctf.id, "web", "xss", 32)

        await overview.update(self.guild, self.ctf.id)

        [message] = self.main.messages
        self.assertEqual(message.content, "**Challenges**\n\n<#21>\n<#32>")
        self.assertTrue(message.pinned)
        self.assertEqual(store.get(self.ctf.id).overview_message_id, message.id)

    async def test_later_updates_edit_the_same_message(self):
        store.add_challenge(self.ctf.id, "web", "xss", 32)
        await overview.update(self.guild, self.ctf.id)
        store.add_challenge(self.ctf.id, "web", "sqli", 31)

        await overview.update(self.guild, self.ctf.id)

        [message] = self.main.messages
        self.assertEqual(message.content, "**Challenges**\n\n<#21>\n<#31>\n<#32>")

    async def test_an_overview_deleted_by_hand_is_posted_and_pinned_again(self):
        store.add_challenge(self.ctf.id, "web", "xss", 32)
        await overview.update(self.guild, self.ctf.id)
        self.main.messages.clear()

        await overview.update(self.guild, self.ctf.id)

        [message] = self.main.messages
        self.assertTrue(message.pinned)
        self.assertEqual(store.get(self.ctf.id).overview_message_id, message.id)

    async def test_an_overview_that_is_not_pinned_is_pinned_again(self):
        store.add_challenge(self.ctf.id, "web", "xss", 32)
        await overview.update(self.guild, self.ctf.id)
        self.main.messages[0].pinned = False

        await overview.update(self.guild, self.ctf.id)

        self.assertTrue(self.main.messages[0].pinned)

    async def test_a_failing_update_is_logged_not_raised(self):
        store.add_challenge(self.ctf.id, "web", "xss", 32)
        self.main.fail = True

        with self.assertLogs("bot", "ERROR"):
            await overview.update(self.guild, self.ctf.id)

    async def test_nothing_happens_for_a_ctf_deleted_meanwhile(self):
        store.delete(self.ctf.id)

        await overview.update(self.guild, self.ctf.id)

        self.assertEqual(self.main.messages, [])

    async def test_nothing_happens_when_the_main_channel_was_deleted_by_hand(self):
        store.add_challenge(self.ctf.id, "web", "xss", 32)

        await overview.update(FakeGuild(), self.ctf.id)

        self.assertIsNone(store.get(self.ctf.id).overview_message_id)


if __name__ == "__main__":
    unittest.main()
