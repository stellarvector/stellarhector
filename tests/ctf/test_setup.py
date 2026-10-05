import itertools
import unittest
from dataclasses import replace

import discord

from ctf import setup, store
from feeds.ctftime import CtftimeError, Event
from tests.factories import SETTINGS, use_temporary_database, utc

_ids = itertools.count(1000)


class DiscordFailure(Exception):
    pass


class FakeRole:
    def __init__(self, guild, name, position=0, color=None, mentionable=False):
        self.guild, self.id, self.name, self.position = guild, next(_ids), name, position
        self.color, self.mentionable = color, mentionable

    async def edit(self, position):
        self.position = position

    async def delete(self):
        self.guild.roles.remove(self)


class FakeMessage:
    def __init__(self, channel, content, view=None):
        self.channel, self.id, self.content, self.view, self.pinned = channel, next(_ids), content, view, False

    async def pin(self):
        self.pinned = True

    async def edit(self, view):
        if self.channel.guild.fail_at == "edit":
            raise DiscordFailure()
        self.view = view

    async def delete(self):
        self.channel.messages.remove(self)


class FakeChannel:
    def __init__(self, guild, name, category=None, overwrites=None, position=None):
        self.guild, self.id, self.name, self.category = guild, next(_ids), name, category
        self.overwrites, self.position = overwrites, position
        self.messages = []

    async def send(self, content, view=None, **kwargs):
        if self.guild.fail_at in ("send", f"send in {self.name}"):
            raise DiscordFailure()
        self.messages.append(FakeMessage(self, content, view))
        return self.messages[-1]

    async def delete(self):
        self.guild.channels.remove(self)


class FakeGuild:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.default_role = FakeRole(self, "@everyone")
        self.me = FakeRole(self, "Stellar Hector")
        self.roles = [self.default_role] + [
            FakeRole(self, name, position)
            for position, name in enumerate(["sv{member}", "sv{moderator}", "sv{manager}", "sv{admin}"], 1)
        ]
        self.channels = []
        # Not in channels: it is there before any CTF is set up, and stays
        self.upcoming = FakeChannel(self, "upcoming-ctfs")

    def get_channel(self, channel_id):
        return next((channel for channel in [*self.channels, self.upcoming] if channel.id == channel_id), None)

    def role(self, name):
        return next(role for role in self.roles if role.name == name)

    def channel(self, name):
        return next(channel for channel in self.channels if channel.name == name)

    async def create_role(self, name, color, mentionable):
        if self.fail_at == "role":
            raise DiscordFailure()
        self.roles.append(FakeRole(self, name, color=color, mentionable=mentionable))
        return self.roles[-1]

    async def create_category(self, name, overwrites):
        if self.fail_at == "category":
            raise DiscordFailure()
        self.channels.append(FakeChannel(self, name, overwrites=overwrites))
        return self.channels[-1]

    async def create_text_channel(self, name, category, overwrites=None, position=None):
        if self.fail_at == name:
            raise DiscordFailure()
        self.channels.append(FakeChannel(self, name, category, overwrites, position))
        return self.channels[-1]


HIDDEN = discord.PermissionOverwrite(view_channel=False)
VISIBLE = discord.PermissionOverwrite(view_channel=True)
BOT = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)


def event(title="Foo CTF 2026"):
    return Event(
        id=3352,
        title=title,
        start=utc(2026, 10, 10, 8),
        finish=utc(2026, 10, 12, 8),
        format="Jeopardy",
        weight=25.0,
        onsite=False,
        url="https://foo.example",
        ctftime_url="https://ctftime.org/event/3352/",
    )


def buttons(view):
    """(label, custom_id) of each button on the view, as Discord gets it."""
    return [(button["label"], button["custom_id"]) for row in view.to_components() for button in row["components"]]


async def no_ctftime(event_id):
    raise AssertionError("CTFtime must not be asked without a CTFtime ID")


class SetupCtfTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.guild = FakeGuild()

    async def setup(self, name="Foo CTF", ctftime_id=None, guild=None, get_event=no_ctftime, upcoming=True):
        guild = guild or self.guild
        settings = replace(
            SETTINGS, channels=replace(SETTINGS.channels, upcoming_ctfs=guild.upcoming.id if upcoming else None)
        )
        return await setup.setup_ctf(guild, name, ctftime_id, settings, get_event=get_event)

    async def test_creates_a_mentionable_role_above_the_member_role(self):
        await self.setup()

        role = self.guild.role("⚡ Foo CTF")
        self.assertEqual(role.color, discord.Color(0x00FF00))
        self.assertTrue(role.mentionable)
        self.assertEqual(role.position, self.guild.role("sv{member}").position + 1)

    async def test_category_is_only_visible_to_the_ctf_role_and_staff(self):
        await self.setup()

        g = self.guild
        self.assertEqual(
            g.channel("⚡ Foo CTF").overwrites,
            {
                g.default_role: HIDDEN,
                g.role("sv{member}"): HIDDEN,
                g.role("⚡ Foo CTF"): VISIBLE,
                g.role("sv{admin}"): discord.PermissionOverwrite(view_channel=True, manage_channels=True),
                g.role("sv{manager}"): VISIBLE,
                g.role("sv{moderator}"): VISIBLE,
                g.me: BOT,
            },
        )

    async def test_main_channel_is_synced_to_the_category_at_the_top(self):
        await self.setup()

        main = self.guild.channel("Foo CTF")
        category = self.guild.channel("⚡ Foo CTF")
        self.assertIs(main.category, category)
        # Discord shows a channel as synced when its overwrites are the category's
        self.assertEqual(main.overwrites, category.overwrites)
        self.assertEqual(main.position, 0)

    async def test_bot_channel_is_only_visible_to_staff(self):
        await self.setup()

        g = self.guild
        bot_channel = g.channel("bot")
        self.assertIs(bot_channel.category, g.channel("⚡ Foo CTF"))
        self.assertEqual(
            bot_channel.overwrites,
            {
                g.default_role: HIDDEN,
                g.role("sv{member}"): HIDDEN,
                g.role("⚡ Foo CTF"): HIDDEN,
                g.role("sv{admin}"): VISIBLE,
                g.role("sv{manager}"): VISIBLE,
                g.role("sv{moderator}"): VISIBLE,
                g.me: BOT,
            },
        )

    async def test_first_message_in_the_main_channel_is_the_pinned_guide(self):
        ctf = await self.setup()

        guide = self.guild.channel("Foo CTF").messages[0]
        self.assertTrue(guide.pinned)
        for command in ["/add-category", "/create-challenge", "/solved"]:
            self.assertIn(command, guide.content)
        self.assertEqual(ctf.guide_message_id, guide.id)

    async def test_guide_has_the_leave_button_of_the_ctf(self):
        ctf = await self.setup()

        guide = self.guild.channel("Foo CTF").messages[0]
        self.assertIn("Leave", guide.content)
        self.assertEqual(buttons(guide.view), [("Leave", f"ctf:leave:{ctf.id}")])

    async def test_posts_the_join_message_with_the_join_button_in_upcoming_ctfs(self):
        ctf = await self.setup()

        join = self.guild.upcoming.messages[0]
        self.assertTrue(join.content.startswith("## :zap: Foo CTF\n"))
        self.assertIn("nobody yet", join.content)
        self.assertEqual(buttons(join.view), [("Join", f"ctf:join:{ctf.id}")])
        self.assertEqual((ctf.join_channel_id, ctf.join_message_id), (self.guild.upcoming.id, join.id))
        self.assertEqual(store.find(name="Foo CTF"), ctf)

    async def test_join_message_shows_the_ctftime_dates(self):
        async def get_event(event_id):
            return event()

        await self.setup(ctftime_id=3352, get_event=get_event)

        self.assertIn("<https://ctftime.org/event/3352/>", self.guild.upcoming.messages[0].content)

    async def test_without_upcoming_ctfs_channel_no_join_message_is_posted(self):
        ctf = await self.setup(upcoming=False)

        self.assertEqual(self.guild.upcoming.messages, [])
        self.assertEqual((ctf.join_channel_id, ctf.join_message_id), (None, None))

    async def test_stores_the_ctf_without_ctftime_data(self):
        ctf = await self.setup()

        g = self.guild
        self.assertEqual(store.find(name="Foo CTF"), ctf)
        self.assertEqual((ctf.ctftime_id, ctf.start, ctf.finish), (None, None, None))
        self.assertEqual(
            (ctf.role_id, ctf.category_id, ctf.main_channel_id, ctf.bot_channel_id),
            (g.role("⚡ Foo CTF").id, g.channel("⚡ Foo CTF").id, g.channel("Foo CTF").id, g.channel("bot").id),
        )

    async def test_with_a_ctftime_id_stores_its_start_and_finish_and_keeps_the_typed_name(self):
        async def get_event(event_id):
            self.assertEqual(event_id, 3352)
            return event()

        ctf = await self.setup(ctftime_id=3352, get_event=get_event)

        self.assertEqual(store.find(ctftime_id=3352), ctf)
        self.assertEqual((ctf.name, ctf.start, ctf.finish), ("Foo CTF", utc(2026, 10, 10, 8), utc(2026, 10, 12, 8)))

    async def test_ctftime_id_that_ctftime_does_not_know_is_refused(self):
        async def get_event(event_id):
            return None

        with self.assertRaisesRegex(setup.SetupRefused, "3352"):
            await self.setup(ctftime_id=3352, get_event=get_event)

        self.assert_nothing_created()

    async def test_ctftime_that_cannot_be_reached_is_refused(self):
        async def get_event(event_id):
            raise CtftimeError("timeout")

        with self.assertRaisesRegex(setup.SetupRefused, "CTFtime"), self.assertLogs("bot", level="WARNING"):
            await self.setup(ctftime_id=3352, get_event=get_event)

        self.assert_nothing_created()

    async def test_duplicate_name_is_refused_with_a_link_to_the_existing_ctf(self):
        existing = await self.setup()
        guild = FakeGuild()

        with self.assertRaisesRegex(setup.SetupRefused, f"<#{existing.main_channel_id}>"):
            await self.setup(name="foo ctf", guild=guild)

        self.assertEqual(guild.channels, [])

    async def test_duplicate_ctftime_id_is_refused_with_a_link_to_the_existing_ctf(self):
        async def get_event(event_id):
            return event()

        existing = await self.setup(ctftime_id=3352, get_event=get_event)
        guild = FakeGuild()

        with self.assertRaisesRegex(setup.SetupRefused, f"<#{existing.main_channel_id}>"):
            await self.setup(name="Other name", ctftime_id=3352, guild=guild, get_event=get_event)

        self.assertEqual(guild.channels, [])

    async def test_discord_error_halfway_removes_what_was_created_and_stores_nothing(self):
        for fail_at in ["role", "category", "Foo CTF", "bot", "send", "edit", "send in upcoming-ctfs"]:
            with self.subTest(fail_at=fail_at):
                guild = FakeGuild(fail_at=fail_at)

                with self.assertRaises(DiscordFailure), self.assertLogs("bot", level="ERROR"):
                    await self.setup(guild=guild)

                self.assertEqual(
                    [role.name for role in guild.roles],
                    ["@everyone", "sv{member}", "sv{moderator}", "sv{manager}", "sv{admin}"],
                )
                self.assertEqual(guild.channels, [])
                self.assertEqual(guild.upcoming.messages, [])
                self.assertIsNone(store.find(name="Foo CTF"))

    def assert_nothing_created(self):
        self.assertEqual(len(self.guild.roles), 5)
        self.assertEqual(self.guild.channels, [])
        self.assertIsNone(store.find(name="Foo CTF"))


if __name__ == "__main__":
    unittest.main()
