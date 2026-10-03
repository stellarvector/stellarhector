import itertools
import tempfile
import unittest
from pathlib import Path

import discord

from core import db
from tests.test_ctfs import new_ctf
from utils import ctf_categories, ctf_places, ctfs

_ids = itertools.count(1000)

STAFF = frozenset({"sv{admin}", "sv{manager}", "sv{moderator}"})


class FakeRole:
    def __init__(self, name):
        self.id, self.name = next(_ids), name


class FakeMember:
    def __init__(self, *roles):
        self.roles = list(roles)


class FakeChannel:
    def __init__(self, guild, name, category=None, overwrites=None, position=0):
        self.guild, self.id, self.name, self.category = guild, next(_ids), name, category
        self.overwrites, self.position = overwrites, position

    @property
    def text_channels(self):
        """As discord.py has them for a category: the channels in it that the guild knows, by position."""
        return sorted((channel for channel in self.guild.known if channel.category is self),
                      key=lambda channel: (channel.position, channel.id))


class FakeHttp:
    def __init__(self, guild):
        self.guild, self.position_updates = guild, 0

    async def bulk_channel_update(self, guild_id, payload):
        assert guild_id == self.guild.id
        self.position_updates += 1
        for update in payload:
            next(channel for channel in self.guild.channels if channel.id == update["id"]).position = update["position"]


class FakeState:
    def __init__(self, guild):
        self.http = FakeHttp(guild)


class FakeGuild:
    """channels are those on Discord; known are those the bot knows of, which lag behind when lagging is set, as when
    the events about new channels did not arrive yet."""
    def __init__(self):
        self.id = next(_ids)
        self.channels, self.known = [], []
        self.fail_at = None
        self.lagging = False
        self._state = FakeState(self)

    def add(self, channel):
        self.channels.append(channel)
        if not self.lagging:
            self.known.append(channel)
        return channel

    def delete(self, channel):
        self.channels.remove(channel)
        self.known.remove(channel)

    def get_channel(self, channel_id):
        return next((channel for channel in self.known if channel.id == channel_id), None)

    async def create_text_channel(self, name, category, overwrites):
        if self.fail_at == name:
            raise discord.DiscordException()
        # Discord puts a new channel at the bottom of its category
        position = 1 + max(channel.position for channel in self.channels if channel.category is category)
        return self.add(FakeChannel(self, name, category, overwrites, position))

    def names(self, category):
        """The names of the channels in the category as Discord shows them."""
        channels = [channel for channel in self.channels if channel.category is category]
        return [channel.name for channel in sorted(channels, key=lambda channel: (channel.position, channel.id))]


class SlugTest(unittest.TestCase):
    def test_lowercase_with_dashes_for_spaces(self):
        self.assertEqual(ctf_categories.slug("Web Exploitation"), "web-exploitation")

    def test_everything_but_letters_digits_and_dashes_is_removed(self):
        self.assertEqual(ctf_categories.slug("🔐 Crypto!"), "crypto")
        self.assertEqual(ctf_categories.slug("re/v_2"), "rev2")

    def test_nothing_left_is_empty(self):
        self.assertEqual(ctf_categories.slug("🔥 ?!"), "")


class SplitNamesTest(unittest.TestCase):
    def test_comma_separated_names_are_trimmed(self):
        self.assertEqual(ctf_categories.split_names("web, crypto ,pwn"), ["web", "crypto", "pwn"])

    def test_one_name(self):
        self.assertEqual(ctf_categories.split_names("reverse engineering"), ["reverse engineering"])

    def test_blank_names_are_left_out(self):
        self.assertEqual(ctf_categories.split_names(" web,, ,crypto, "), ["web", "crypto"])


class MayPlayTest(unittest.TestCase):
    def setUp(self):
        self.ctf_role = FakeRole("⚡ Foo CTF")
        self.ctf = new_ctf(role_id=self.ctf_role.id)

    def test_players_of_the_ctf_may(self):
        self.assertTrue(ctf_places.may_play(FakeMember(FakeRole("sv{member}"), self.ctf_role), self.ctf, STAFF))

    def test_staff_may(self):
        for name in STAFF:
            with self.subTest(name):
                self.assertTrue(ctf_places.may_play(FakeMember(FakeRole(name)), self.ctf, STAFF))

    def test_others_may_not(self):
        other_ctf_role = FakeRole("⚡ Bar CTF")

        self.assertFalse(ctf_places.may_play(FakeMember(FakeRole("sv{member}"), other_ctf_role), self.ctf, STAFF))


class AddCategoriesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)

        self.guild = FakeGuild()
        self.category = self.guild.add(FakeChannel(self.guild, "⚡ Foo CTF", overwrites={"ctf role": "visible"}))
        self.main = self.guild.add(FakeChannel(self.guild, "Foo CTF", self.category, position=0))
        self.bot = self.guild.add(FakeChannel(self.guild, "bot", self.category, position=1))
        self.ctf = ctfs.create(new_ctf(category_id=self.category.id, main_channel_id=self.main.id,
                                       bot_channel_id=self.bot.id))

    async def add(self, names):
        return await ctf_categories.add_categories(self.guild, self.ctf, names)

    async def test_creates_a_channel_per_category_in_the_ctf_category_synced_to_it(self):
        added = await self.add("web, crypto")

        self.assertEqual([channel.name for channel in added.created], ["crypto", "web"])
        for channel in added.created:
            self.assertIn(channel, self.guild.channels)
            self.assertIs(channel.category, self.category)
            self.assertIs(channel.category, self.category)
            self.assertEqual(channel.overwrites, self.category.overwrites)

    async def test_categories_are_in_alphabetical_order_below_the_main_channel(self):
        await self.add("web, crypto")
        await self.add("pwn, a-first, zz-last")

        self.assertEqual(self.guild.names(self.category),
                         ["Foo CTF", "a-first", "crypto", "pwn", "web", "zz-last", "bot"])

    async def test_order_is_right_when_the_guild_does_not_know_the_new_channels_yet(self):
        self.guild.lagging = True

        await self.add("web, crypto, pwn")

        self.assertEqual(self.guild.names(self.category), ["Foo CTF", "crypto", "pwn", "web", "bot"])
        self.assertEqual(self.guild._state.http.position_updates, 1)

    async def test_other_channels_in_the_category_stay_below_the_categories_in_their_order(self):
        notes = self.guild.add(FakeChannel(self.guild, "notes", self.category, position=2))
        self.guild.add(FakeChannel(self.guild, "aaa-voice-chat", self.category, position=3))

        await self.add("web")

        self.assertEqual(self.guild.names(self.category), ["Foo CTF", "web", "bot", "notes", "aaa-voice-chat"])
        self.assertIs(notes.category, self.category)

    async def test_nothing_is_moved_when_nothing_is_created(self):
        await self.add("web")

        await self.add("web, 🔥")

        self.assertEqual(self.guild._state.http.position_updates, 1)

    async def test_names_are_slugified(self):
        added = await self.add("Web Exploitation, 🔐 Crypto")

        self.assertEqual([channel.name for channel in added.created], ["crypto", "web-exploitation"])

    async def test_categories_are_stored(self):
        added = await self.add("web, crypto")

        self.assertEqual(ctfs.categories(self.ctf.id),
                         [ctfs.Category("crypto", added.created[0].id), ctfs.Category("web", added.created[1].id)])

    async def test_an_existing_category_is_skipped_and_reported(self):
        first = await self.add("web")

        added = await self.add("web, Crypto, WEB")

        self.assertEqual([channel.name for channel in added.created], ["crypto"])
        self.assertEqual(added.existing, [ctfs.Category("web", first.created[0].id)])
        self.assertEqual(self.guild.names(self.category).count("web"), 1)

    async def test_a_category_whose_channel_was_deleted_by_hand_is_created_again(self):
        first = await self.add("web, crypto")
        self.guild.delete(first.created[1])

        added = await self.add("web")

        [web] = added.created
        self.assertEqual(web.name, "web")
        self.assertEqual(ctfs.categories(self.ctf.id),
                         [ctfs.Category("crypto", first.created[0].id), ctfs.Category("web", web.id)])
        self.assertEqual(self.guild.names(self.category), ["Foo CTF", "crypto", "web", "bot"])

    async def test_a_category_named_twice_is_created_once(self):
        added = await self.add("web, Web")

        self.assertEqual([channel.name for channel in added.created], ["web"])
        self.assertEqual(added.existing, [])

    async def test_a_name_with_nothing_left_after_slugifying_is_skipped_and_reported(self):
        added = await self.add("🔥, web, ?!")

        self.assertEqual([channel.name for channel in added.created], ["web"])
        self.assertEqual(added.invalid, ["🔥", "?!"])

    async def test_categories_of_another_ctf_do_not_count(self):
        other = ctfs.create(new_ctf(name="Bar CTF", category_id=90, main_channel_id=91, bot_channel_id=92))
        ctfs.add_category(other.id, "web", 93)

        added = await self.add("web")

        self.assertEqual([channel.name for channel in added.created], ["web"])

    async def test_discord_error_keeps_the_categories_made_before_it(self):
        self.guild.fail_at = "web"

        with self.assertRaises(discord.DiscordException):
            await self.add("web, crypto")

        self.assertEqual([category.slug for category in ctfs.categories(self.ctf.id)], ["crypto"])
        self.assertEqual(self.guild.names(self.category), ["Foo CTF", "crypto", "bot"])
        added = await self.add("crypto")
        self.assertEqual(added.created, [])


class ReportTest(unittest.TestCase):
    def test_lists_what_was_created_existed_and_was_skipped(self):
        added = ctf_categories.Added(created=[FakeChannel(None, "crypto")],
                                     existing=[ctfs.Category("web", 7)], invalid=["🔥"])

        self.assertEqual(ctf_categories.report(added),
                         f"Created <#{added.created[0].id}> :muscle:\n"
                         "Already exists: <#7>\n"
                         "Skipped `🔥`: a category name needs letters or digits")

    def test_only_the_parts_that_apply(self):
        self.assertEqual(ctf_categories.report(ctf_categories.Added(existing=[ctfs.Category("web", 7)])),
                         "Already exists: <#7>")

    def test_no_names(self):
        self.assertEqual(ctf_categories.report(ctf_categories.Added()),
                         "Give the category names, comma-separated: `/add-category web, crypto, pwn`")


if __name__ == "__main__":
    unittest.main()
