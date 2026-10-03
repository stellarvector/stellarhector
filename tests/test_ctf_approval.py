import asyncio
import itertools
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import discord

from core import db
from utils import ctf_join, ctfs
from utils.ctf_join import Decision

_ids = itertools.count(1000)

ROLES = ctf_join.JoinRoles(trusted=frozenset({"sv{core-player}", "sv{known-player}", "sv{admin}", "sv{manager}",
                                              "sv{moderator}"}),
                           player="sv{player}")
APPROVAL_ROLES = ctf_join.ApprovalRoles(staff=frozenset({"sv{admin}", "sv{manager}", "sv{moderator}"}),
                                        known_player="sv{known-player}")


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def http_error(error, status):
    return error(SimpleNamespace(status=status, reason=error.__name__), "fake")


class FakeRole:
    def __init__(self, name, position=0):
        self.id, self.name, self.position = next(_ids), name, position


class FakeMember:
    def __init__(self, guild, *role_names, joined_at=utc(2025, 9, 1, 12), dms_closed=False):
        self.guild, self.id, self.joined_at, self.dms_closed = guild, next(_ids), joined_at, dms_closed
        self.roles_fail = False
        self.roles = [guild.default_role] + [guild.role(name) for name in role_names]
        self.dms = []
        guild.members.append(self)

    @property
    def mention(self):
        return f"<@{self.id}>"

    async def add_roles(self, *roles):
        # Let other clicks run in between, as a real request to Discord would
        await asyncio.sleep(0)
        if self.roles_fail:
            raise http_error(discord.HTTPException, 500)
        self.roles += [role for role in roles if role not in self.roles]

    async def remove_roles(self, *roles):
        self.roles = [role for role in self.roles if role not in roles]

    async def send(self, content):
        if self.dms_closed:
            raise http_error(discord.Forbidden, 403)
        self.dms.append(content)


class FakeMessage:
    def __init__(self, content, view=None):
        self.id, self.content, self.view = next(_ids), content, view

    async def edit(self, content, allowed_mentions=None):
        self.content = content


class FakeChannel:
    def __init__(self, name):
        self.id, self.name, self.messages = next(_ids), name, []

    async def send(self, content, view=None, allowed_mentions=None):
        self.messages.append(FakeMessage(content, view))
        return self.messages[-1]

    def get_partial_message(self, message_id):
        return next(message for message in self.messages if message.id == message_id)


class FakeGuild:
    def __init__(self):
        self.default_role = FakeRole("@everyone")
        self.roles = [self.default_role] + [FakeRole(name, position) for position, name in enumerate(
            ["sv{member}", "sv{player}", "sv{known-player}", "sv{core-player}", "sv{moderator}", "sv{manager}",
             "sv{admin}", "Foo CTF"], 1)]
        self.channels = [FakeChannel("upcoming-ctfs"), FakeChannel("foo-ctf"), FakeChannel("bot")]
        self.members = []

    def role(self, name):
        return next(role for role in self.roles if role.name == name)

    def channel(self, name):
        return next(channel for channel in self.channels if channel.name == name)

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)

    def get_channel(self, channel_id):
        return next((channel for channel in self.channels if channel.id == channel_id), None)

    def get_member(self, user_id):
        return next((member for member in self.members if member.id == user_id), None)

    async def fetch_member(self, user_id):
        member = self.get_member(user_id)
        if member is None:
            raise http_error(discord.NotFound, 404)
        return member


class FakeResponse:
    async def defer(self, **kwargs):
        pass


class FakeInteraction:
    """A click by user on a button of message (None for a reply to the click that is not a message edit)."""
    def __init__(self, user, guild, custom_id, message=None, edit_fails=False):
        self.user, self.guild, self.message, self.edit_fails = user, guild, message, edit_fails
        self.data = {"custom_id": custom_id}
        self.response = FakeResponse()
        self.followup = SimpleNamespace(send=self._reply)
        self.replies = []

    async def _reply(self, content, ephemeral=False):
        self.replies.append((content, ephemeral))

    async def edit_original_response(self, content, view, allowed_mentions=None):
        if self.edit_fails:
            raise http_error(discord.NotFound, 404)
        self.message.content, self.message.view = content, view


class FakeClient:
    def add_dynamic_items(self, *items):
        pass


def buttons(view):
    """(label, custom_id) of each button on the view, as Discord gets it."""
    return [(button["label"], button["custom_id"]) for row in view.to_components() for button in row["components"]]


class ApprovalCardTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)
        ctf_join.register(FakeClient(), ROLES, APPROVAL_ROLES)

        self.guild = FakeGuild()
        upcoming = self.guild.channel("upcoming-ctfs")
        self.ctf = ctfs.create(ctfs.NewCtf(
            name="Foo CTF", ctftime_id=None, start=None, finish=None, role_id=self.guild.role("Foo CTF").id,
            category_id=1, main_channel_id=self.guild.channel("foo-ctf").id,
            bot_channel_id=self.guild.channel("bot").id, guide_message_id=2))
        self.join_message = FakeMessage("join message")
        upcoming.messages.append(self.join_message)
        ctfs.set_join_message(self.ctf.id, upcoming.id, self.join_message.id)
        self.ctf = ctfs.get(self.ctf.id)

        self.player = FakeMember(self.guild, "sv{member}", "sv{player}")
        self.moderator = FakeMember(self.guild, "sv{member}", "sv{moderator}")

    async def join(self, member):
        interaction = FakeInteraction(member, self.guild, f"ctf:join:{self.ctf.id}")
        await ctf_join.JoinButton(self.ctf.id).callback(interaction)
        return interaction.replies

    def cards(self):
        return self.guild.channel("bot").messages

    async def click(self, member, decision, card=None, edit_fails=False):
        """member clicks the decision button on the card (the player's latest by default); returns the replies."""
        card = card or self.cards()[-1]
        custom_id = f"ctf:card:{decision.value}:{self.ctf.id}:{self.player.id}"
        interaction = FakeInteraction(member, self.guild, custom_id, card, edit_fails)
        await ctf_join.ApprovalButton(decision, self.ctf.id, self.player.id).callback(interaction)
        return interaction.replies

    def assert_still_pending(self, card):
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id).status, "pending")
        self.assertIsNotNone(card.view)
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_plain_players_join_posts_a_card_in_the_ctfs_bot_channel_with_their_details_and_three_buttons(self):
        other = ctfs.create(ctfs.NewCtf(name="Bar CTF", ctftime_id=None, start=None, finish=None, role_id=3,
                                        category_id=4, main_channel_id=5, bot_channel_id=6, guide_message_id=7))
        ctfs.add_player(other.id, self.player.id, utc(2026, 9, 1, 12))

        self.assertEqual(await self.join(self.player), [("Waiting for moderator confirmation", True)])

        [card] = self.cards()
        p, ctf = self.player.id, self.ctf.id
        self.assertEqual(card.content,
                         f":raising_hand: <@{p}> wants to join **Foo CTF**\n"
                         f"**Roles:** <@&{self.guild.role('sv{player}').id}>, <@&{self.guild.role('sv{member}').id}>\n"
                         f"**On the server since:** <t:1756728000:D> (<t:1756728000:R>)\n"
                         f"**CTFs joined before:** 1")
        self.assertEqual(buttons(card.view), [("Accept", f"ctf:card:accept:{ctf}:{p}"),
                                              ("Accept + known player", f"ctf:card:known:{ctf}:{p}"),
                                              ("Decline", f"ctf:card:decline:{ctf}:{p}")])
        self.assertEqual(ctfs.player(ctf, p).approval_card_message_id, card.id)

    async def test_accept_gives_the_ctf_role_and_shows_them_on_the_join_message(self):
        await self.join(self.player)
        [card] = self.cards()

        self.assertEqual(await self.click(self.moderator, Decision.ACCEPT), [])

        self.assertIn(self.guild.role("Foo CTF"), self.player.roles)
        self.assertNotIn(self.guild.role("sv{known-player}"), self.player.roles)
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id).status, "joined")
        self.assertIn(f"**Playing (1):** <@{self.player.id}>", self.join_message.content)
        self.assertTrue(card.content.endswith(f"**CTFs joined before:** 0\n"
                                              f":white_check_mark: Accepted by <@{self.moderator.id}>"))
        self.assertIsNone(card.view)

    async def test_accept_as_known_player_also_gives_the_known_player_role(self):
        await self.join(self.player)
        [card] = self.cards()

        await self.click(self.moderator, Decision.ACCEPT_KNOWN)

        self.assertIn(self.guild.role("Foo CTF"), self.player.roles)
        self.assertIn(self.guild.role("sv{known-player}"), self.player.roles)
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id).status, "joined")
        self.assertTrue(card.content.endswith(
            f"\n:white_check_mark: Accepted as known player by <@{self.moderator.id}>"))
        self.assertIsNone(card.view)

    async def test_decline_dms_the_player_and_lets_them_ask_again_later(self):
        await self.join(self.player)
        [card] = self.cards()

        await self.click(self.moderator, Decision.DECLINE)

        self.assertEqual(self.player.dms,
                         ["For now it was not possible to join **Foo CTF**, go see a moderator on-site."])
        self.assertIsNone(ctfs.player(self.ctf.id, self.player.id))
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)
        self.assertTrue(card.content.endswith(f"\n:x: Declined by <@{self.moderator.id}>"))
        self.assertIsNone(card.view)

        self.assertEqual(await self.join(self.player), [("Waiting for moderator confirmation", True)])
        self.assertEqual(len(self.cards()), 2)

    async def test_decline_whose_dm_cannot_be_delivered_says_so_on_the_card(self):
        self.player.dms_closed = True
        await self.join(self.player)
        [card] = self.cards()

        self.assertEqual(await self.click(self.moderator, Decision.DECLINE), [])

        self.assertIsNone(ctfs.player(self.ctf.id, self.player.id))
        self.assertTrue(card.content.endswith(f"\n:x: Declined by <@{self.moderator.id}> (DM failed)"))

    async def test_every_staff_role_can_decide(self):
        for staff in ("sv{admin}", "sv{manager}", "sv{moderator}"):
            with self.subTest(staff):
                ctfs.remove_player(self.ctf.id, self.player.id)
                await self.join(self.player)

                await self.click(FakeMember(self.guild, staff), Decision.DECLINE)

                self.assertIsNone(self.cards()[-1].view)

    async def test_non_staff_cannot_decide(self):
        await self.join(self.player)
        [card] = self.cards()
        core_player = FakeMember(self.guild, "sv{member}", "sv{core-player}")

        for clicker in (core_player, self.player):
            with self.subTest(clicker=clicker.id):
                self.assertEqual(await self.click(clicker, Decision.ACCEPT),
                                 [(":no_entry: Only admins, managers and moderators can decide on this request.", True)])
                self.assert_still_pending(card)

    async def test_a_click_on_a_handled_card_does_nothing(self):
        await self.join(self.player)
        [card] = self.cards()
        await self.click(self.moderator, Decision.DECLINE)
        handled = card.content

        self.assertEqual(await self.click(self.moderator, Decision.ACCEPT),
                         [("This request was already handled.", True)])

        self.assertEqual(card.content, handled)
        self.assertIsNone(ctfs.player(self.ctf.id, self.player.id))
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_two_staff_clicking_at_once_only_the_first_decides(self):
        await self.join(self.player)
        [card] = self.cards()
        admin = FakeMember(self.guild, "sv{admin}")

        first, second = await asyncio.gather(self.click(self.moderator, Decision.ACCEPT),
                                             self.click(admin, Decision.DECLINE))

        self.assertEqual((first, second), ([], [("This request was already handled.", True)]))
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id).status, "joined")
        self.assertEqual(self.player.dms, [])
        self.assertTrue(card.content.endswith(f"\n:white_check_mark: Accepted by <@{self.moderator.id}>"))

    async def test_a_card_whose_player_left_the_ctf_meanwhile_was_already_handled(self):
        await self.join(self.player)
        ctfs.remove_player(self.ctf.id, self.player.id)

        self.assertEqual(await self.click(self.moderator, Decision.ACCEPT),
                         [("This request was already handled.", True)])
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_an_older_card_of_someone_asking_again_was_already_handled(self):
        await self.join(self.player)
        old = self.cards()[0]
        await self.click(self.moderator, Decision.DECLINE)
        await self.join(self.player)

        self.assertEqual(await self.click(self.moderator, Decision.ACCEPT, card=old),
                         [("This request was already handled.", True)])
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id).status, "pending")

    async def test_someone_who_left_the_server_cannot_be_accepted_but_can_be_declined(self):
        await self.join(self.player)
        [card] = self.cards()
        self.guild.members.remove(self.player)

        self.assertEqual(await self.click(self.moderator, Decision.ACCEPT),
                         [(f"<@{self.player.id}> is no longer on the server, **Decline** to close this request.",
                           True)])
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id).status, "pending")
        self.assertIsNotNone(card.view)

        await self.click(self.moderator, Decision.DECLINE)

        self.assertIsNone(ctfs.player(self.ctf.id, self.player.id))
        self.assertTrue(card.content.endswith(f"\n:x: Declined by <@{self.moderator.id}> (left the server)"))

    async def test_accept_that_discord_refuses_leaves_the_request_open_to_try_again(self):
        await self.join(self.player)
        [card] = self.cards()
        asked = ctfs.player(self.ctf.id, self.player.id)
        self.player.roles_fail = True

        with self.assertLogs("bot", "ERROR"):
            replies = await self.click(self.moderator, Decision.ACCEPT)

        self.assertEqual(replies, [("Sorry, an unknown error occurred, please ask a moderator for help.", True)])
        self.assertEqual(ctfs.player(self.ctf.id, self.player.id), asked)
        self.assert_still_pending(card)

        self.player.roles_fail = False
        await self.click(self.moderator, Decision.ACCEPT)

        self.assertIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_decision_on_a_card_that_cannot_be_edited_is_told_to_the_clicker(self):
        await self.join(self.player)

        with self.assertLogs("bot", "ERROR"):
            replies = await self.click(self.moderator, Decision.DECLINE, edit_fails=True)

        self.assertEqual(replies, [(f":x: Declined by <@{self.moderator.id}>, but the card could not be updated.",
                                    True)])
        self.assertIsNone(ctfs.player(self.ctf.id, self.player.id))

    async def test_without_a_known_player_role_configured_the_card_has_no_known_player_button(self):
        ctf_join.register(FakeClient(), ROLES, ctf_join.ApprovalRoles(staff=APPROVAL_ROLES.staff, known_player=None))

        await self.join(self.player)

        self.assertEqual([label for label, _ in buttons(self.cards()[-1].view)], ["Accept", "Decline"])

    async def test_the_buttons_find_their_ctf_and_player_from_the_custom_id_after_a_restart(self):
        match = ctf_join.ApprovalButton.__discord_ui_compiled_template__.fullmatch(
            f"ctf:card:known:{self.ctf.id}:{self.player.id}")

        button = await ctf_join.ApprovalButton.from_custom_id(None, None, match)

        self.assertEqual((button.decision, button.ctf_id, button.user_id),
                         (Decision.ACCEPT_KNOWN, self.ctf.id, self.player.id))


if __name__ == "__main__":
    unittest.main()
