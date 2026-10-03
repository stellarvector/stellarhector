import itertools
import tempfile
import unittest
from pathlib import Path

import discord

from core import db
from tests.test_ctfs import new_ctf
from utils import ctf_challenges, ctfs
from utils.ctf_places import locate

_ids = itertools.count(1000)


class FakeUser:
    def __init__(self):
        self.id = next(_ids)
        self.mention = f"<@{self.id}>"


class FakeThread:
    def __init__(self, guild, parent, name, auto_archive_duration):
        self.guild, self.id, self.parent, self.name = guild, next(_ids), parent, name
        self.auto_archive_duration, self.archived, self.members = auto_archive_duration, False, []
        self.mention = f"<#{self.id}>"

    async def add_user(self, user):
        if self.archived:
            raise discord.DiscordException("adding to an archived thread")
        if user not in self.members:
            self.members.append(user)

    async def edit(self, archived):
        self.archived = archived


class FakeMessage:
    def __init__(self, channel, content, allowed_mentions):
        self.channel, self.content, self.allowed_mentions = channel, content, allowed_mentions
        self.thread = None

    async def delete(self):
        self.channel.messages.remove(self)

    async def create_thread(self, name, auto_archive_duration):
        if self.channel.guild.fail_threads:
            raise discord.DiscordException()
        self.thread = self.channel.guild.add(FakeThread(self.channel.guild, self.channel, name, auto_archive_duration))
        return self.thread


class FakeChannel:
    def __init__(self, guild, category_id=None, channel_id=None):
        self.guild, self.category_id, self.id = guild, category_id, channel_id or next(_ids)
        self.messages = []

    async def send(self, content, allowed_mentions):
        self.messages.append(FakeMessage(self, content, allowed_mentions))
        return self.messages[-1]


class FakeGuild:
    """threads are those on Discord; cached are those the bot has in its cache, which leaves out archived ones."""
    def __init__(self):
        self.threads, self.cached = [], []
        self.fail_threads = False

    def add(self, thread):
        self.threads.append(thread)
        self.cached.append(thread)
        return thread

    def get_channel_or_thread(self, channel_id):
        return next((thread for thread in self.cached if thread.id == channel_id), None)

    async def fetch_channel(self, channel_id):
        found = next((thread for thread in self.threads if thread.id == channel_id), None)
        if found is None:
            raise discord.NotFound(FakeResponse(), "Unknown Channel")
        return found


class FakeResponse:
    status, reason = 404, "Not Found"


class StartTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)

        self.guild = FakeGuild()
        self.ctf = ctfs.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        self.web = FakeChannel(self.guild, category_id=2)
        ctfs.add_category(self.ctf.id, "web", self.web.id)
        self.alice, self.bob = FakeUser(), FakeUser()

    async def start(self, user, slug, channel=None):
        channel = channel or self.web
        return await ctf_challenges.start(self.guild, self.ctf, ctfs.Category("web", channel.id), channel, user, slug)

    async def test_a_new_challenge_gets_a_public_thread_on_a_starter_message_with_the_user_in_it(self):
        started = await self.start(self.alice, "xss")

        [message] = self.web.messages
        self.assertEqual(message.content, f"🧩 `xss`, started by {self.alice.mention}")
        self.assertIs(started.thread, message.thread)
        self.assertEqual(started.thread.name, "xss")
        self.assertEqual(started.thread.auto_archive_duration, 10080)
        self.assertEqual(started.thread.members, [self.alice])
        self.assertTrue(started.created)

    async def test_the_starter_message_pings_nobody(self):
        await self.start(self.alice, "xss")

        mentions = self.web.messages[0].allowed_mentions
        self.assertFalse(mentions.users or mentions.roles or mentions.everyone)

    async def test_a_new_challenge_is_stored_unsolved(self):
        started = await self.start(self.alice, "xss")

        self.assertEqual(ctfs.challenge(self.ctf.id, "web", "xss"),
                         ctfs.Challenge("web", "xss", started.thread.id, solved=False))

    async def test_an_existing_challenge_adds_the_user_to_its_thread_without_a_new_one(self):
        first = await self.start(self.alice, "xss")

        started = await self.start(self.bob, "xss")

        self.assertIs(started.thread, first.thread)
        self.assertFalse(started.created)
        self.assertEqual(started.thread.members, [self.alice, self.bob])
        self.assertEqual(len(self.web.messages), 1)

    async def test_a_solved_challenge_is_found_by_its_slug_although_its_thread_was_renamed(self):
        first = await self.start(self.alice, "xss")
        first.thread.name = "✅ xss"

        started = await self.start(self.bob, "xss")

        self.assertIs(started.thread, first.thread)
        self.assertIn(self.bob, first.thread.members)

    async def test_an_archived_thread_is_unarchived_and_the_user_added(self):
        first = await self.start(self.alice, "xss")
        first.thread.archived = True
        self.guild.cached.remove(first.thread)

        started = await self.start(self.bob, "xss")

        self.assertIs(started.thread, first.thread)
        self.assertFalse(started.thread.archived)
        self.assertIn(self.bob, started.thread.members)

    async def test_a_thread_deleted_by_hand_is_made_again(self):
        first = await self.start(self.alice, "xss")
        self.guild.threads.remove(first.thread)
        self.guild.cached.remove(first.thread)

        started = await self.start(self.bob, "xss")

        self.assertIsNot(started.thread, first.thread)
        self.assertTrue(started.created)
        self.assertEqual(started.thread.members, [self.bob])
        self.assertEqual(ctfs.challenge(self.ctf.id, "web", "xss").thread_id, started.thread.id)

    async def test_a_solved_challenge_whose_thread_was_deleted_gets_a_thread_marked_solved(self):
        first = await self.start(self.alice, "xss")
        with db.transaction() as conn:
            conn.execute("UPDATE ctf_challenges SET solved = 1")
        self.guild.threads.remove(first.thread)
        self.guild.cached.remove(first.thread)

        started = await self.start(self.bob, "xss")

        self.assertEqual(started.thread.name, "✅ xss")
        self.assertTrue(ctfs.challenge(self.ctf.id, "web", "xss").solved)

    async def test_the_starter_message_is_deleted_when_the_thread_cannot_be_made(self):
        self.guild.fail_threads = True

        with self.assertRaises(discord.DiscordException):
            await self.start(self.alice, "xss")

        self.assertEqual(self.web.messages, [])
        self.assertIsNone(ctfs.challenge(self.ctf.id, "web", "xss"))

    async def test_the_same_slug_in_another_category_is_another_challenge(self):
        pwn = FakeChannel(self.guild, category_id=2)
        ctfs.add_category(self.ctf.id, "pwn", pwn.id)
        first = await self.start(self.alice, "baby")

        started = await ctf_challenges.start(self.guild, self.ctf, ctfs.Category("pwn", pwn.id), pwn, self.bob, "baby")

        self.assertIsNot(started.thread, first.thread)
        self.assertTrue(started.created)


class CategoryOfTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)
        self.ctf = ctfs.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        self.web = FakeChannel(None, category_id=2)
        ctfs.add_category(self.ctf.id, "web", self.web.id)

    def test_a_category_channel_is_its_category(self):
        self.assertEqual(ctf_challenges.category_of(locate(self.web)), ctfs.Category("web", self.web.id))

    def test_a_challenge_thread_is_in_its_parent_channels_category(self):
        thread = FakeThread(None, self.web, "xss", 10080)

        self.assertEqual(ctf_challenges.category_of(locate(thread)), ctfs.Category("web", self.web.id))

    def test_anywhere_else_is_no_category(self):
        main, bot = FakeChannel(None, 2, channel_id=3), FakeChannel(None, 2, channel_id=4)
        made_by_hand = FakeChannel(None, category_id=2)
        outside = FakeChannel(None, category_id=99)

        for channel in [main, bot, made_by_hand, outside, FakeThread(None, main, "chat", 10080)]:
            with self.subTest(channel):
                self.assertIsNone(ctf_challenges.category_of(locate(channel)))


class ReplyTest(unittest.TestCase):
    def test_new_challenge_links_its_thread(self):
        thread = FakeThread(None, None, "xss", 10080)

        self.assertEqual(ctf_challenges.reply(ctf_challenges.Started(thread, "xss", created=True)),
                         f"Started {thread.mention}, go solve that thing :muscle:")

    def test_existing_challenge_points_to_its_thread(self):
        thread = FakeThread(None, None, "xss", 10080)

        self.assertEqual(ctf_challenges.reply(ctf_challenges.Started(thread, "xss", created=False)),
                         f"`xss` already exists, you were added to {thread.mention}")


if __name__ == "__main__":
    unittest.main()
