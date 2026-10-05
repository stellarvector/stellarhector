import itertools
import unittest
from dataclasses import replace

import discord

from ctf import buttons, lock, store
from ctf.models import NewCtf
from tests.factories import ROLES, use_temporary_database, utc
from tests.fakes import FakeCategory, FakeCategoryChannel, FakeGuild, FakeMessage, http_error

NOW = utc(2026, 10, 17, 8)

_HIDDEN = discord.PermissionOverwrite(view_channel=False)
_VISIBLE = discord.PermissionOverwrite(view_channel=True)
_WRITING = (
    "send_messages",
    "send_messages_in_threads",
    "create_public_threads",
    "create_private_threads",
    "add_reactions",
)


_thread_ids = itertools.count(1)


class FakeThread:
    def __init__(self, name, archived=False, private=False):
        self.id = next(_thread_ids)
        self.name, self.archived, self.locked, self.private = name, archived, False, private

    async def edit(self, archived=None, locked=None):
        # As Discord: an archived thread can only be changed by unarchiving it in the same request
        if self.archived and archived is not False:
            raise http_error(discord.HTTPException, 400)
        if archived is not None:
            self.archived = archived
        if locked is not None:
            self.locked = locked


class FakeThreadedChannel(FakeCategoryChannel):
    """A channel in the CTF's category with threads: the active ones as discord.py caches them, the archived ones only
    known by asking Discord, public and private apart."""

    def __init__(self, name, category, overwrites):
        super().__init__(name, category, overwrites)
        self.active, self.archived = [], []

    @property
    def threads(self):
        return list(self.active)

    async def archived_threads(self, private=False, limit=100):
        for thread in self.archived:
            if thread.private == private:
                yield thread

    def thread(self, name, archived=False, private=False):
        thread = FakeThread(name, archived, private)
        (self.archived if archived else self.active).append(thread)
        return thread


class FakeStaleCategory(FakeCategory):
    """A category as discord.py caches it: an edit changes it on Discord, but the cached overwrites only follow when
    Discord's update event comes in, or when it is fetched."""

    def __init__(self, overwrites):
        super().__init__(overwrites)
        self.on_discord = overwrites

    async def edit(self, overwrites):
        self.edits += 1
        self.on_discord = overwrites

    def fetched(self):
        self.overwrites = self.on_discord
        return self


class FakeArchive:
    """Stands in for archiving the CTF (generating the pages and the git work): records its calls, or fails."""

    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def __call__(self, guild, ctf, now):
        self.calls.append((guild, ctf.id, now))
        if self.error is not None:
            raise self.error


class LockTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.guild = FakeGuild()
        self.bot_user = object()
        everyone, member, ctf_role = (
            self.guild.default_role,
            self.guild.role("sv{member}"),
            self.guild.role("Foo CTF"),
        )
        admin, manager, moderator = (self.guild.role(name) for name in ("sv{admin}", "sv{manager}", "sv{moderator}"))
        self.bot_overwrite = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        self.admin_overwrite = discord.PermissionOverwrite(view_channel=True, manage_channels=True)
        self.category = FakeCategory(
            {
                everyone: _HIDDEN,
                member: _HIDDEN,
                ctf_role: _VISIBLE,
                admin: self.admin_overwrite,
                manager: _VISIBLE,
                moderator: _VISIBLE,
                self.bot_user: self.bot_overwrite,
            }
        )
        self.guild.channels = [self.guild.channel("upcoming-ctfs"), self.category]
        self.main, self.web = (
            FakeThreadedChannel(name, self.category, dict(self.category.overwrites)) for name in ("foo-ctf", "web")
        )
        self.bot_overwrites = {everyone: _HIDDEN, member: _HIDDEN, ctf_role: _HIDDEN, manager: _VISIBLE}
        self.bot_channel = FakeThreadedChannel("bot", self.category, dict(self.bot_overwrites))
        self.category.channels = [self.main, self.bot_channel, self.web]
        self.guild.channels += self.category.channels

        upcoming = self.guild.channel("upcoming-ctfs")
        ctf = store.create(
            NewCtf(
                name="Foo CTF",
                ctftime_id=None,
                start=None,
                finish=None,
                role_id=ctf_role.id,
                category_id=self.category.id,
                main_channel_id=self.main.id,
                bot_channel_id=self.bot_channel.id,
                guide_message_id=2,
            )
        )
        self.join_message = FakeMessage("join message", buttons.join_view(ctf.id))
        upcoming.messages.append(self.join_message)
        store.set_join_message(ctf.id, upcoming.id, self.join_message.id)
        self.ctf = store.get(ctf.id)
        self.archive = FakeArchive()

        async def fetch_channel(channel_id):
            return self.guild.get_channel(channel_id)

        self.guild.fetch_channel = fetch_channel

    async def lock(self, ctf=None, roles=ROLES):
        return await lock.lock_ctf(self.guild, ctf or self.ctf, roles, NOW, self.archive)

    def assert_cannot_write(self, overwrite):
        for permission in _WRITING:
            self.assertIs(getattr(overwrite, permission), False, permission)

    def assert_can_write(self, overwrite):
        for permission in _WRITING:
            self.assertIs(getattr(overwrite, permission), True, permission)

    async def test_everyone_members_and_players_can_read_but_not_write(self):
        await self.lock()

        overwrites = self.category.overwrites
        for name in ("@everyone", "sv{member}", "Foo CTF"):
            with self.subTest(name):
                self.assert_cannot_write(overwrites[self.guild.role(name)])
        self.assertIs(overwrites[self.guild.role("sv{member}")].view_channel, True)
        self.assertIs(overwrites[self.guild.role("Foo CTF")].view_channel, True)
        self.assertIs(overwrites[self.guild.default_role].view_channel, False)

    async def test_admins_managers_and_moderators_keep_writing(self):
        await self.lock()

        overwrites = self.category.overwrites
        for name in ("sv{admin}", "sv{manager}", "sv{moderator}"):
            with self.subTest(name):
                self.assert_can_write(overwrites[self.guild.role(name)])
                self.assertIs(overwrites[self.guild.role(name)].view_channel, True)
        self.assertIs(overwrites[self.guild.role("sv{admin}")].manage_channels, True)
        self.assertEqual(overwrites[self.bot_user], self.bot_overwrite)

    async def test_every_channel_but_bot_is_synced_to_the_category(self):
        await self.lock()

        for channel in (self.main, self.web):
            self.assertEqual(channel.overwrites, self.category.overwrites)
        self.assertEqual(self.bot_channel.overwrites, self.bot_overwrites)

    async def test_every_thread_in_the_ctf_is_archived_and_locked(self):
        threads = [
            self.web.thread("sqli"),
            self.web.thread("✅-xss", archived=True),
            self.web.thread("by-hand", private=True),
            self.web.thread("old-private", archived=True, private=True),
            self.main.thread("chat"),
        ]

        await self.lock()

        for thread in threads:
            with self.subTest(thread.name):
                self.assertEqual((thread.archived, thread.locked), (True, True))

    async def test_threads_in_bot_are_left_alone(self):
        thread = self.bot_channel.thread("staff")

        await self.lock()

        self.assertEqual((thread.archived, thread.locked), (False, False))

    async def test_a_ctf_that_was_not_released_is_released_first(self):
        locked = (await self.lock()).ctf

        self.assertEqual(locked.released_at, NOW)
        self.assertIn("**Joining is closed:**", self.join_message.content)

    async def test_a_released_ctf_is_locked_as_it_is(self):
        store.mark_released(self.ctf.id, utc(2026, 10, 14, 8))
        self.join_message.content = "released join message"

        # As read before the release: what is stored counts
        locked = (await self.lock(self.ctf)).ctf

        self.assertEqual(locked.released_at, utc(2026, 10, 14, 8))
        self.assertEqual(locked.locked_at, NOW)
        self.assertEqual(self.join_message.content, "released join message")

    async def test_records_the_lock_time_and_then_archives(self):
        archive_saw = []

        async def archive(guild, ctf, now):
            archive_saw.append((store.get(ctf.id).locked_at, [thread.locked for thread in self.web.threads]))

        self.archive = archive
        self.web.thread("sqli")

        result = await self.lock()

        self.assertEqual(result.ctf, store.get(self.ctf.id))
        self.assertEqual(result.ctf.locked_at, NOW)
        self.assertIsNone(result.archive_error)
        self.assertEqual(archive_saw, [(NOW, [True])])

    async def test_archives_the_ctf_at_the_lock_time(self):
        await self.lock()

        self.assertEqual(self.archive.calls, [(self.guild, self.ctf.id, NOW)])

    async def test_an_archive_failure_is_logged_and_returned_and_the_lock_stays(self):
        error = RuntimeError("push rejected")
        self.archive = FakeArchive(error)
        thread = self.web.thread("sqli")

        with self.assertLogs("bot", "ERROR"):
            result = await self.lock()

        self.assertIs(result.archive_error, error)
        self.assertEqual(result.ctf.locked_at, NOW)
        self.assertEqual((thread.archived, thread.locked), (True, True))
        self.assert_cannot_write(self.category.overwrites[self.guild.role("sv{member}")])

    async def test_a_second_run_changes_nothing_and_says_so(self):
        await self.lock()
        self.category.edits = 0
        thread = self.web.thread("reopened")

        with self.assertRaisesRegex(lock.LockRefused, r"\*\*Foo CTF\*\* was already locked"):
            await self.lock()

        self.assertEqual(self.category.edits, 0)
        self.assertFalse(thread.locked)
        self.assertEqual(len(self.archive.calls), 1)

    async def test_a_second_run_after_a_failed_archive_points_to_archive_ctf(self):
        self.archive = FakeArchive(RuntimeError("push rejected"))
        with self.assertLogs("bot", "ERROR"):
            await self.lock()

        with self.assertRaisesRegex(lock.LockRefused, "was not archived.*`/archive-ctf`"):
            await self.lock()

    async def test_refused_without_the_member_role(self):
        for member in (None, "sv{nonexistent}"):
            with self.subTest(member):
                with self.assertRaisesRegex(lock.LockRefused, "member role"):
                    await self.lock(roles=replace(ROLES, member=member))

                self.assertEqual(self.category.edits, 0)
                self.assertIsNone(store.get(self.ctf.id).locked_at)

    async def test_refused_when_the_category_no_longer_exists(self):
        self.guild.channels.remove(self.category)

        with self.assertRaisesRegex(lock.LockRefused, "category"):
            await self.lock()

        self.assertIsNone(store.get(self.ctf.id).locked_at)
        self.assertEqual(self.archive.calls, [])

    async def test_builds_on_the_category_as_released_also_before_discord_tells_the_bot(self):
        stale = FakeStaleCategory(self.category.overwrites)
        stale.id, stale.channels = self.category.id, self.category.channels
        self.guild.channels[self.guild.channels.index(self.category)] = stale
        get_channel = self.guild.fetch_channel

        async def fetch_channel(channel_id):
            return stale.fetched() if channel_id == stale.id else await get_channel(channel_id)

        self.guild.fetch_channel = fetch_channel

        await self.lock()

        member = stale.on_discord[self.guild.role("sv{member}")]
        self.assertIs(member.view_channel, True)
        self.assert_cannot_write(member)

    async def test_a_ctf_role_deleted_by_hand_is_skipped(self):
        self.guild.roles.remove(self.guild.role("Foo CTF"))

        result = await self.lock()

        self.assertEqual(result.ctf.locked_at, NOW)
        self.assertNotIn(None, self.category.overwrites)
        self.assert_cannot_write(self.category.overwrites[self.guild.role("sv{member}")])

    async def test_a_channel_without_threads_in_the_category_is_synced_too(self):
        voice = FakeCategoryChannel("voice", self.category, {})
        self.category.channels.append(voice)

        await self.lock()

        self.assertEqual(voice.overwrites, self.category.overwrites)


if __name__ == "__main__":
    unittest.main()
