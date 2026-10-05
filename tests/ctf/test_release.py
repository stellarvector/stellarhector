import unittest
from dataclasses import replace

import discord

from cogs import players
from ctf import buttons, release, store
from ctf.buttons import Decision
from ctf.models import NewCtf, PlayerStatus
from tests.factories import ROLES, use_temporary_database, utc
from tests.fakes import (
    FakeCategory,
    FakeCategoryChannel,
    FakeGuild,
    FakeInteraction,
    FakeMember,
    FakeMessage,
    http_error,
)

NOW = utc(2026, 10, 13, 8)

_HIDDEN = discord.PermissionOverwrite(view_channel=False)
_VISIBLE = discord.PermissionOverwrite(view_channel=True)


class ReleaseTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.guild = FakeGuild()
        self.bot_user = object()
        everyone, member, ctf_role, manager = (
            self.guild.default_role,
            self.guild.role("sv{follower}"),
            self.guild.role("Foo CTF"),
            self.guild.role("sv{manager}"),
        )
        self.bot_overwrite = discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True)
        self.category = FakeCategory(
            {
                everyone: _HIDDEN,
                member: _HIDDEN,
                ctf_role: _VISIBLE,
                manager: _VISIBLE,
                self.bot_user: self.bot_overwrite,
            }
        )
        self.guild.channels = [self.guild.channel("upcoming-ctfs"), self.category]
        self.main, self.web = (
            FakeCategoryChannel(name, self.category, dict(self.category.overwrites)) for name in ("foo-ctf", "web")
        )
        self.bot_channel = FakeCategoryChannel(
            "bot", self.category, {everyone: _HIDDEN, member: _HIDDEN, ctf_role: _HIDDEN, manager: _VISIBLE}
        )
        self.category.channels = [self.main, self.bot_channel, self.web]
        self.guild.channels += self.category.channels

        self.upcoming = self.guild.channel("upcoming-ctfs")
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
        self.upcoming.messages.append(self.join_message)
        store.set_join_message(ctf.id, self.upcoming.id, self.join_message.id)

        self.player = FakeMember(self.guild, "sv{follower}", "sv{core-player}")
        store.add_player(ctf.id, self.player.id, utc(2026, 10, 1, 12))
        self.ctf = store.get(ctf.id)

    async def ask_to_join(self):
        """A plain player clicks Join: they wait on an approval card in #bot, which is returned."""
        member = FakeMember(self.guild, "sv{follower}", "sv{player}")
        await players.JoinButton(self.ctf.id).callback(FakeInteraction(member, self.guild, f"ctf:join:{self.ctf.id}"))
        return member, self.bot_channel.messages[-1]

    async def release(self, ctf=None, roles=ROLES):
        return await release.release_ctf(self.guild, ctf or self.ctf, roles, NOW)

    async def test_members_can_read_and_write_in_the_ctf_channels_but_not_in_bot(self):
        bot_overwrites = dict(self.bot_channel.overwrites)

        await self.release()

        for name in ("sv{player}", "sv{follower}"):
            with self.subTest(name):
                member = self.category.overwrites[self.guild.role(name)]
                self.assertEqual(member, _VISIBLE)
                # Nothing denied: they write as they do anywhere on the server, also in the (public) challenge threads
                self.assertEqual(member.pair()[1].value, 0)
        for channel in (self.main, self.web):
            self.assertEqual(channel.overwrites, self.category.overwrites)
        self.assertEqual(self.bot_channel.overwrites, bot_overwrites)

    async def test_everything_else_keeps_its_permissions(self):
        await self.release()

        self.assertEqual(self.category.overwrites[self.guild.default_role], _HIDDEN)
        self.assertEqual(self.category.overwrites[self.guild.role("Foo CTF")], _VISIBLE)
        self.assertEqual(self.category.overwrites[self.guild.role("sv{manager}")], _VISIBLE)
        self.assertEqual(self.category.overwrites[self.bot_user], self.bot_overwrite)

    async def test_join_message_says_joining_is_closed_and_its_button_is_disabled(self):
        await self.release()

        self.assertEqual(
            self.join_message.content,
            f"## :unlock: Foo CTF\n**Playing (1):** <@{self.player.id}>\n"
            f"**Joining is closed:** the CTF is open to all members, see <#{self.main.id}>",
        )
        [[button]] = [row["components"] for row in self.join_message.view.to_components()]
        self.assertEqual(
            (button["label"], button["custom_id"], button["disabled"]), ("Join", f"ctf:join:{self.ctf.id}", True)
        )

    async def test_join_message_keeps_saying_so_when_someone_leaves_afterwards(self):
        await self.release()

        await players.LeaveButton(self.ctf.id).callback(
            FakeInteraction(self.player, self.guild, f"ctf:leave:{self.ctf.id}")
        )

        self.assertEqual(
            self.join_message.content,
            f"## :unlock: Foo CTF\n**Playing:** nobody\n"
            f"**Joining is closed:** the CTF is open to all members, see <#{self.main.id}>",
        )

    async def test_pending_approval_cards_are_closed_and_their_players_taken_off_the_list(self):
        waiting, card = await self.ask_to_join()
        content = card.content

        await self.release()

        self.assertEqual(card.content, f"{content}\n:lock: No longer needed: CTF released")
        self.assertIsNone(card.view)
        self.assertIsNone(store.player(self.ctf.id, waiting.id))
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.JOINED)

    async def test_a_click_on_a_closed_card_meanwhile_is_told_it_was_handled(self):
        waiting, card = await self.ask_to_join()
        moderator = FakeMember(self.guild, "sv{follower}", "sv{moderator}")
        await self.release()

        interaction = FakeInteraction(moderator, self.guild, f"ctf:card:accept:{self.ctf.id}:{waiting.id}", card)
        await players.DecisionButton(Decision.ACCEPT, self.ctf.id, waiting.id).callback(interaction)

        self.assertEqual(interaction.replies, [("This request was already handled.", True)])
        self.assertNotIn(self.guild.role("Foo CTF"), waiting.roles)

    async def test_a_card_posted_while_releasing_is_closed_and_the_player_told_joining_is_closed(self):
        waiting = FakeMember(self.guild, "sv{follower}", "sv{player}")
        send = self.bot_channel.send

        async def send_during_release(*args, **kwargs):
            await self.release()
            return await send(*args, **kwargs)

        self.bot_channel.send = send_during_release

        interaction = FakeInteraction(waiting, self.guild, f"ctf:join:{self.ctf.id}")
        await players.JoinButton(self.ctf.id).callback(interaction)

        [card] = self.bot_channel.messages
        self.assertTrue(card.content.endswith("\n:lock: No longer needed: CTF released"))
        self.assertIsNone(card.view)
        self.assertEqual(interaction.replies, [(":no_entry: Joining **Foo CTF** is closed.", True)])
        self.assertIsNone(store.player(self.ctf.id, waiting.id))

    async def test_an_accept_that_fails_after_the_release_does_not_wait_again(self):
        waiting, card = await self.ask_to_join()
        moderator = FakeMember(self.guild, "sv{follower}", "sv{moderator}")
        add_roles = waiting.add_roles

        async def fail_after_release(*roles):
            await self.release()
            waiting.roles_fail = True
            await add_roles(*roles)

        waiting.add_roles = fail_after_release

        interaction = FakeInteraction(moderator, self.guild, f"ctf:card:accept:{self.ctf.id}:{waiting.id}", card)
        with self.assertLogs("bot", "ERROR"):
            await players.DecisionButton(Decision.ACCEPT, self.ctf.id, waiting.id).callback(interaction)

        self.assertIsNone(store.player(self.ctf.id, waiting.id))

    async def test_records_the_release_time(self):
        ctf = await self.release()

        self.assertEqual(ctf, store.get(self.ctf.id))
        self.assertEqual(ctf.released_at, NOW)

    async def test_a_second_run_changes_nothing_and_says_so(self):
        released = await self.release()
        self.category.overwrites[self.guild.role("sv{follower}")] = _HIDDEN
        self.join_message.content = "join message"

        with self.assertRaisesRegex(release.ReleaseRefused, r"\*\*Foo CTF\*\* was already released"):
            await self.release(released)

        self.assertEqual(self.category.edits, 1)
        self.assertEqual(self.join_message.content, "join message")
        self.assertEqual(store.get(self.ctf.id).released_at, NOW)

    async def test_a_run_with_the_ctf_as_read_before_another_release_changes_nothing(self):
        await self.release()

        with self.assertRaises(release.ReleaseRefused):
            await self.release(self.ctf)

        self.assertEqual(self.category.edits, 1)

    async def test_a_missing_follower_role_does_not_keep_the_players_out(self):
        with self.assertLogs("bot", "WARNING"):
            await self.release(roles=replace(ROLES, follower="sv{nonexistent}"))

        self.assertEqual(self.category.overwrites[self.guild.role("sv{player}")], _VISIBLE)
        self.assertEqual(store.get(self.ctf.id).released_at, NOW)

    async def test_refused_without_any_member_role(self):
        for role in (None, "sv{nonexistent}"):
            with self.subTest(role):
                with self.assertRaisesRegex(release.ReleaseRefused, "player nor the follower role"):
                    await self.release(roles=replace(ROLES, player=role, follower=role))

                self.assertEqual(self.category.edits, 0)
                self.assertIsNone(store.get(self.ctf.id).released_at)

    async def test_refused_when_the_category_no_longer_exists(self):
        self.guild.channels.remove(self.category)

        with self.assertRaisesRegex(release.ReleaseRefused, "category"):
            await self.release()

        self.assertIsNone(store.get(self.ctf.id).released_at)

    async def test_ctf_without_a_join_message_is_released(self):
        store.set_join_message(self.ctf.id, None, None)

        ctf = await self.release(store.get(self.ctf.id))

        self.assertEqual(ctf.released_at, NOW)
        self.assertEqual(self.join_message.content, "join message")

    async def test_join_message_or_card_deleted_by_hand_is_fine(self):
        waiting, card = await self.ask_to_join()
        self.upcoming.messages.remove(self.join_message)
        self.bot_channel.messages.remove(card)

        with self.assertLogs("bot", "WARNING"):
            ctf = await self.release()

        self.assertEqual(ctf.released_at, NOW)
        self.assertIsNone(store.player(self.ctf.id, waiting.id))

    async def test_a_card_that_cannot_be_edited_is_logged_and_the_others_are_closed(self):
        _, first = await self.ask_to_join()
        _, second = await self.ask_to_join()

        async def refuse(**kwargs):
            raise http_error(discord.HTTPException, 500)

        first.edit = refuse

        with self.assertLogs("bot", "ERROR"):
            await self.release()

        self.assertIsNone(second.view)


if __name__ == "__main__":
    unittest.main()
