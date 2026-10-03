import itertools
import tempfile
import unittest
from pathlib import Path

import discord

from core import db
from tests.test_ctfs import new_ctf
from utils import ctf_overview, ctfs
from utils.ctfs import Category, Challenge

_ids = itertools.count(5000)


class TextTest(unittest.TestCase):
    def test_challenges_are_grouped_under_their_category_channel(self):
        categories = [Category("crypto", 20), Category("web", 21)]
        challenges = [Challenge("crypto", "rsa", 30, solved=True), Challenge("web", "sqli", 31, solved=False),
                      Challenge("web", "xss", 32, solved=False)]

        self.assertEqual(ctf_overview.text(categories, challenges),
                         "**Challenges**\n\n<#20>\n<#30>\n\n<#21>\n<#31>\n<#32>")

    def test_categories_without_challenges_are_left_out(self):
        categories = [Category("crypto", 20), Category("web", 21)]

        self.assertEqual(ctf_overview.text(categories, [Challenge("web", "xss", 32, solved=False)]),
                         "**Challenges**\n\n<#21>\n<#32>")

    def test_a_category_not_stored_is_named_by_its_slug(self):
        self.assertEqual(ctf_overview.text([], [Challenge("web", "xss", 32, solved=False)]),
                         "**Challenges**\n\n**web**\n<#32>")

    def test_everything_is_shown_when_it_fits_the_limit_exactly(self):
        challenges = [Challenge("web", "xss", 32, solved=False)]
        full = ctf_overview.text([Category("web", 21)], challenges)

        self.assertEqual(ctf_overview.text([Category("web", 21)], challenges, limit=len(full)), full)

    def test_a_long_overview_is_cut_and_says_how_many_are_left_out(self):
        categories = [Category("crypto", 20), Category("web", 21)]
        challenges = [Challenge("crypto", "a", 30, solved=False), Challenge("crypto", "b", 31, solved=False),
                      Challenge("web", "c", 32, solved=False)]
        # Room for the title, crypto and its first challenge, and the line saying the rest is left out
        limit = len("**Challenges**\n\n<#20>\n<#30>\n\n… and 2 more")

        self.assertEqual(ctf_overview.text(categories, challenges, limit=limit),
                         "**Challenges**\n\n<#20>\n<#30>\n\n… and 2 more")

    def test_a_category_header_is_not_shown_without_any_of_its_challenges(self):
        categories = [Category("crypto", 20), Category("web", 21)]
        challenges = [Challenge("crypto", "a", 30, solved=False), Challenge("web", "b", 31, solved=False),
                      Challenge("web", "c", 32, solved=False)]
        # Room for the web header, but not for its first challenge too
        limit = len("**Challenges**\n\n<#20>\n<#30>\n\n<#21>\n\n… and 2 more")

        self.assertEqual(ctf_overview.text(categories, challenges, limit=limit),
                         "**Challenges**\n\n<#20>\n<#30>\n\n… and 2 more")

    def test_many_challenges_stay_within_discords_message_limit(self):
        categories = [Category(f"cat{c}", 10**18 + c) for c in range(5)]
        challenges = [Challenge(f"cat{c}", f"chal{i:03}", 10**18 + 100 * c + i, solved=i % 2 == 0)
                      for c in range(5) for i in range(30)]

        text = ctf_overview.text(categories, challenges)

        self.assertLessEqual(len(text), 2000)
        shown = text.count("<#") - text.count("\n\n<#")
        self.assertTrue(text.endswith(f"… and {150 - shown} more"))


class FakeMessage:
    def __init__(self, channel, content):
        self.channel, self.id, self.content, self.pinned = channel, next(_ids), content, False

    async def pin(self):
        if self.channel.fail:
            raise discord.HTTPException(FakeResponse(), "Maximum number of pins reached")
        self.pinned = True


class FakePartialMessage:
    def __init__(self, channel, message_id):
        self.channel, self.id = channel, message_id

    async def edit(self, content):
        message = next((message for message in self.channel.messages if message.id == self.id), None)
        if message is None:
            raise discord.NotFound(FakeResponse(), "Unknown Message")
        if self.channel.fail:
            raise discord.HTTPException(FakeResponse(), "Missing Permissions")
        message.content = content
        return message


class FakeResponse:
    status, reason = 404, "Not Found"


class FakeChannel:
    def __init__(self, channel_id):
        self.id, self.messages, self.fail = channel_id, [], False

    async def send(self, content, allowed_mentions):
        self.messages.append(FakeMessage(self, content))
        return self.messages[-1]

    def get_partial_message(self, message_id):
        return FakePartialMessage(self, message_id)


class FakeGuild:
    def __init__(self, *channels):
        self.channels = list(channels)

    def get_channel(self, channel_id):
        return next((channel for channel in self.channels if channel.id == channel_id), None)


class UpdateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)

        self.main = FakeChannel(3)
        self.guild = FakeGuild(self.main)
        self.ctf = ctfs.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        ctfs.add_category(self.ctf.id, "web", 21)

    async def test_nothing_is_posted_before_the_first_challenge(self):
        await ctf_overview.update(self.guild, self.ctf.id)

        self.assertEqual(self.main.messages, [])

    async def test_the_first_update_posts_and_pins_the_overview_in_the_main_channel(self):
        ctfs.add_challenge(self.ctf.id, "web", "xss", 32)

        await ctf_overview.update(self.guild, self.ctf.id)

        [message] = self.main.messages
        self.assertEqual(message.content, "**Challenges**\n\n<#21>\n<#32>")
        self.assertTrue(message.pinned)
        self.assertEqual(ctfs.get(self.ctf.id).overview_message_id, message.id)

    async def test_later_updates_edit_the_same_message(self):
        ctfs.add_challenge(self.ctf.id, "web", "xss", 32)
        await ctf_overview.update(self.guild, self.ctf.id)
        ctfs.add_challenge(self.ctf.id, "web", "sqli", 31)

        await ctf_overview.update(self.guild, self.ctf.id)

        [message] = self.main.messages
        self.assertEqual(message.content, "**Challenges**\n\n<#21>\n<#31>\n<#32>")

    async def test_an_overview_deleted_by_hand_is_posted_and_pinned_again(self):
        ctfs.add_challenge(self.ctf.id, "web", "xss", 32)
        await ctf_overview.update(self.guild, self.ctf.id)
        self.main.messages.clear()

        await ctf_overview.update(self.guild, self.ctf.id)

        [message] = self.main.messages
        self.assertTrue(message.pinned)
        self.assertEqual(ctfs.get(self.ctf.id).overview_message_id, message.id)

    async def test_an_overview_that_is_not_pinned_is_pinned_again(self):
        ctfs.add_challenge(self.ctf.id, "web", "xss", 32)
        await ctf_overview.update(self.guild, self.ctf.id)
        self.main.messages[0].pinned = False

        await ctf_overview.update(self.guild, self.ctf.id)

        self.assertTrue(self.main.messages[0].pinned)

    async def test_a_failing_update_is_logged_not_raised(self):
        ctfs.add_challenge(self.ctf.id, "web", "xss", 32)
        self.main.fail = True

        with self.assertLogs("bot", "ERROR"):
            await ctf_overview.update(self.guild, self.ctf.id)

    async def test_nothing_happens_for_a_ctf_deleted_meanwhile(self):
        ctfs.delete(self.ctf.id)

        await ctf_overview.update(self.guild, self.ctf.id)

        self.assertEqual(self.main.messages, [])

    async def test_nothing_happens_when_the_main_channel_was_deleted_by_hand(self):
        ctfs.add_challenge(self.ctf.id, "web", "xss", 32)

        await ctf_overview.update(FakeGuild(), self.ctf.id)

        self.assertIsNone(ctfs.get(self.ctf.id).overview_message_id)


if __name__ == "__main__":
    unittest.main()
