import itertools
import unittest

import discord

from core import db
from ctf import challenges, store
from ctf.location import locate
from ctf.models import Category, Challenge
from tests.factories import new_ctf, use_temporary_database
from tests.fakes import PinningChannel

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

    async def edit(self, name=None, archived=None):
        if self.guild.fail_edits:
            raise discord.DiscordException()
        if self.archived and archived is not False:
            raise discord.DiscordException("editing an archived thread")
        self.name = self.name if name is None else name
        self.archived = self.archived if archived is None else archived


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

    def __init__(self, main=None):
        self.threads, self.cached, self.main = [], [], main
        self.fail_threads = self.fail_edits = False

    def get_channel(self, channel_id):
        return self.main if self.main is not None and self.main.id == channel_id else None

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


class ChallengeTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.main = PinningChannel(3)
        self.guild = FakeGuild(self.main)
        self.ctf = store.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        self.web = FakeChannel(self.guild, category_id=2)
        store.add_category(self.ctf.id, "web", self.web.id)
        self.alice, self.bob = FakeUser(), FakeUser()

    async def start(self, user, slug, channel=None):
        channel = channel or self.web
        return await challenges.start_challenge(self.guild, self.ctf, Category("web", channel.id), channel, user, slug)


class StartTest(ChallengeTestCase):
    async def test_a_new_challenge_gets_a_public_thread_on_a_starter_message_with_the_user_in_it(self):
        started = await self.start(self.alice, "xss")

        [message] = self.web.messages
        self.assertEqual(message.content, f"🧩 `xss`, started by {self.alice.mention}")
        self.assertIs(started.thread, message.thread)
        self.assertEqual(started.thread.name, "xss")
        self.assertEqual(started.thread.auto_archive_duration, 10080)
        self.assertEqual(started.thread.members, [self.alice])
        self.assertTrue(started.created)

    async def test_a_new_challenge_is_put_in_the_overview(self):
        first = await self.start(self.alice, "xss")
        second = await self.start(self.alice, "sqli")

        [overview] = self.main.messages
        self.assertEqual(
            overview.content, f"**Challenges**\n\n<#{self.web.id}>\n{second.thread.mention}\n{first.thread.mention}"
        )

    async def test_the_starter_message_pings_nobody(self):
        await self.start(self.alice, "xss")

        mentions = self.web.messages[0].allowed_mentions
        self.assertFalse(mentions.users or mentions.roles or mentions.everyone)

    async def test_a_new_challenge_is_stored_unsolved(self):
        started = await self.start(self.alice, "xss")

        self.assertEqual(
            store.challenge(self.ctf.id, "web", "xss"), Challenge("web", "xss", started.thread.id, solved=False)
        )

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
        self.assertEqual(store.challenge(self.ctf.id, "web", "xss").thread_id, started.thread.id)

    async def test_a_solved_challenge_whose_thread_was_deleted_gets_a_thread_marked_solved(self):
        first = await self.start(self.alice, "xss")
        with db.transaction() as conn:
            conn.execute("UPDATE ctf_challenges SET solved = 1")
        self.guild.threads.remove(first.thread)
        self.guild.cached.remove(first.thread)

        started = await self.start(self.bob, "xss")

        self.assertEqual(started.thread.name, "✅ xss")
        self.assertTrue(store.challenge(self.ctf.id, "web", "xss").solved)

    async def test_the_starter_message_is_deleted_when_the_thread_cannot_be_made(self):
        self.guild.fail_threads = True

        with self.assertRaises(discord.DiscordException):
            await self.start(self.alice, "xss")

        self.assertEqual(self.web.messages, [])
        self.assertIsNone(store.challenge(self.ctf.id, "web", "xss"))

    async def test_the_same_slug_in_another_category_is_another_challenge(self):
        pwn = FakeChannel(self.guild, category_id=2)
        store.add_category(self.ctf.id, "pwn", pwn.id)
        first = await self.start(self.alice, "baby")

        started = await challenges.start_challenge(self.guild, self.ctf, Category("pwn", pwn.id), pwn, self.bob, "baby")

        self.assertIsNot(started.thread, first.thread)
        self.assertTrue(started.created)


class MarkSolvedTest(ChallengeTestCase):
    async def asyncSetUp(self):
        self.thread = (await self.start(self.alice, "xss")).thread

    async def mark(self, solved):
        challenge = store.challenge(self.ctf.id, "web", "xss")
        return await challenges.mark_solved(self.guild, self.ctf, self.thread, challenge, solved)

    async def test_solving_renames_the_thread_keeps_it_open_and_stores_it(self):
        self.assertTrue(await self.mark(True))

        self.assertEqual(self.thread.name, "✅ xss")
        self.assertFalse(self.thread.archived)
        self.assertTrue(store.challenge(self.ctf.id, "web", "xss").solved)

    async def test_solving_a_solved_challenge_changes_nothing(self):
        await self.mark(True)
        self.thread.name = "renamed by hand"

        self.assertFalse(await self.mark(True))

        self.assertEqual(self.thread.name, "renamed by hand")

    async def test_unsolving_renames_the_thread_back_and_stores_it(self):
        await self.mark(True)

        self.assertTrue(await self.mark(False))

        self.assertEqual(self.thread.name, "xss")
        self.assertFalse(store.challenge(self.ctf.id, "web", "xss").solved)

    async def test_unsolving_an_unsolved_challenge_changes_nothing(self):
        self.assertFalse(await self.mark(False))

        self.assertEqual(self.thread.name, "xss")

    async def test_an_archived_thread_is_unarchived_to_rename_it(self):
        self.thread.archived = True

        await self.mark(True)

        self.assertEqual(self.thread.name, "✅ xss")
        self.assertFalse(self.thread.archived)

    async def test_the_challenge_stays_as_it_was_when_the_thread_cannot_be_renamed(self):
        self.guild.fail_edits = True

        with self.assertRaises(discord.DiscordException):
            await self.mark(True)

        self.assertFalse(store.challenge(self.ctf.id, "web", "xss").solved)

    async def test_an_overview_deleted_by_hand_is_posted_again(self):
        self.main.messages.clear()

        await self.mark(True)

        [overview] = self.main.messages
        self.assertIn(self.thread.mention, overview.content)


class ChallengeAtTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        self.web = FakeChannel(None, category_id=2)
        store.add_category(self.ctf.id, "web", self.web.id)

    def test_a_stored_challenge_thread_is_its_challenge(self):
        thread = FakeThread(None, self.web, "xss", 10080)
        store.add_challenge(self.ctf.id, "web", "xss", thread.id)

        self.assertEqual(
            challenges.challenge_at(locate(thread), thread), Challenge("web", "xss", thread.id, solved=False)
        )

    def test_a_thread_not_made_by_create_challenge_is_no_challenge(self):
        thread = FakeThread(None, self.web, "chat", 10080)

        self.assertIsNone(challenges.challenge_at(locate(thread), thread))

    def test_a_category_channel_is_no_challenge(self):
        self.assertIsNone(challenges.challenge_at(locate(self.web), self.web))


class CategoryOfTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf(category_id=2, main_channel_id=3, bot_channel_id=4))
        self.web = FakeChannel(None, category_id=2)
        store.add_category(self.ctf.id, "web", self.web.id)

    def test_a_category_channel_is_its_category(self):
        self.assertEqual(challenges.category_of(locate(self.web)), Category("web", self.web.id))

    def test_a_challenge_thread_is_in_its_parent_channels_category(self):
        thread = FakeThread(None, self.web, "xss", 10080)

        self.assertEqual(challenges.category_of(locate(thread)), Category("web", self.web.id))

    def test_anywhere_else_is_no_category(self):
        main, bot = FakeChannel(None, 2, channel_id=3), FakeChannel(None, 2, channel_id=4)
        made_by_hand = FakeChannel(None, category_id=2)
        outside = FakeChannel(None, category_id=99)

        for channel in [main, bot, made_by_hand, outside, FakeThread(None, main, "chat", 10080)]:
            with self.subTest(channel):
                self.assertIsNone(challenges.category_of(locate(channel)))


if __name__ == "__main__":
    unittest.main()
