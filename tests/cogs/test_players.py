import asyncio
import unittest
from dataclasses import replace

from cogs import players
from ctf import store
from ctf.buttons import Decision
from ctf.models import NewCtf, PlayerStatus
from tests.factories import SETTINGS, use_temporary_database, utc
from tests.fakes import FakeGuild, FakeInteraction, FakeMember, FakeMessage, buttons


class ApprovalCardTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.guild = FakeGuild()
        upcoming = self.guild.channel("upcoming-ctfs")
        self.ctf = store.create(
            NewCtf(
                name="Foo CTF",
                ctftime_id=None,
                start=None,
                finish=None,
                role_id=self.guild.role("Foo CTF").id,
                category_id=1,
                main_channel_id=self.guild.channel("foo-ctf").id,
                bot_channel_id=self.guild.channel("bot").id,
                guide_message_id=2,
            )
        )
        self.join_message = FakeMessage("join message")
        upcoming.messages.append(self.join_message)
        store.set_join_message(self.ctf.id, upcoming.id, self.join_message.id)
        self.ctf = store.get(self.ctf.id)

        self.player = FakeMember(self.guild, "sv{member}", "sv{player}")
        self.moderator = FakeMember(self.guild, "sv{member}", "sv{moderator}")
        self.settings = SETTINGS

    def interaction(self, *args):
        interaction = FakeInteraction(*args)
        interaction.client.settings = self.settings
        return interaction

    async def join(self, member):
        interaction = self.interaction(member, self.guild, f"ctf:join:{self.ctf.id}")
        await players.JoinButton(self.ctf.id).callback(interaction)
        return interaction.replies

    def cards(self):
        return self.guild.channel("bot").messages

    async def click(self, member, decision, card=None, edit_fails=False):
        """member clicks the decision button on the card (the player's latest by default); returns the replies."""
        card = card or self.cards()[-1]
        custom_id = f"ctf:card:{decision.value}:{self.ctf.id}:{self.player.id}"
        interaction = self.interaction(member, self.guild, custom_id, card, edit_fails)
        await players.DecisionButton(decision, self.ctf.id, self.player.id).callback(interaction)
        return interaction.replies

    def assert_still_pending(self, card):
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.PENDING)
        self.assertIsNotNone(card.view)
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_plain_players_join_posts_a_card_in_the_ctfs_bot_channel_with_their_details_and_three_buttons(self):
        other = store.create(
            NewCtf(
                name="Bar CTF",
                ctftime_id=None,
                start=None,
                finish=None,
                role_id=3,
                category_id=4,
                main_channel_id=5,
                bot_channel_id=6,
                guide_message_id=7,
            )
        )
        store.add_player(other.id, self.player.id, utc(2026, 9, 1, 12))

        self.assertEqual(await self.join(self.player), [("Waiting for moderator confirmation", True)])

        [card] = self.cards()
        p, ctf = self.player.id, self.ctf.id
        self.assertEqual(
            card.content,
            f":raising_hand: <@{p}> wants to join **Foo CTF**\n"
            f"**Roles:** <@&{self.guild.role('sv{player}').id}>, <@&{self.guild.role('sv{member}').id}>\n"
            f"**On the server since:** <t:1756728000:D> (<t:1756728000:R>)\n"
            f"**CTFs joined before:** 1",
        )
        self.assertEqual(
            buttons(card.view),
            [
                ("Accept", f"ctf:card:accept:{ctf}:{p}"),
                ("Accept + known player", f"ctf:card:known:{ctf}:{p}"),
                ("Decline", f"ctf:card:decline:{ctf}:{p}"),
            ],
        )
        self.assertEqual(store.player(ctf, p).approval_card_message_id, card.id)

    async def test_accept_gives_the_ctf_role_and_shows_them_on_the_join_message(self):
        await self.join(self.player)
        [card] = self.cards()

        self.assertEqual(await self.click(self.moderator, Decision.ACCEPT), [])

        self.assertIn(self.guild.role("Foo CTF"), self.player.roles)
        self.assertNotIn(self.guild.role("sv{known-player}"), self.player.roles)
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.JOINED)
        self.assertIn(f"**Playing (1):** <@{self.player.id}>", self.join_message.content)
        self.assertTrue(
            card.content.endswith(f"**CTFs joined before:** 0\n:white_check_mark: Accepted by <@{self.moderator.id}>")
        )
        self.assertIsNone(card.view)

    async def test_accept_as_known_player_also_gives_the_known_player_role(self):
        await self.join(self.player)
        [card] = self.cards()

        await self.click(self.moderator, Decision.ACCEPT_KNOWN)

        self.assertIn(self.guild.role("Foo CTF"), self.player.roles)
        self.assertIn(self.guild.role("sv{known-player}"), self.player.roles)
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.JOINED)
        self.assertTrue(
            card.content.endswith(f"\n:white_check_mark: Accepted as known player by <@{self.moderator.id}>")
        )
        self.assertIsNone(card.view)

    async def test_decline_dms_the_player_and_lets_them_ask_again_later(self):
        await self.join(self.player)
        [card] = self.cards()

        await self.click(self.moderator, Decision.DECLINE)

        self.assertEqual(
            self.player.dms, ["For now it was not possible to join **Foo CTF**, go see a moderator on-site."]
        )
        self.assertIsNone(store.player(self.ctf.id, self.player.id))
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

        self.assertIsNone(store.player(self.ctf.id, self.player.id))
        self.assertTrue(card.content.endswith(f"\n:x: Declined by <@{self.moderator.id}> (DM failed)"))

    async def test_every_staff_role_can_decide(self):
        for staff in ("sv{admin}", "sv{manager}", "sv{moderator}"):
            with self.subTest(staff):
                store.remove_player(self.ctf.id, self.player.id)
                await self.join(self.player)

                await self.click(FakeMember(self.guild, staff), Decision.DECLINE)

                self.assertIsNone(self.cards()[-1].view)

    async def test_non_staff_cannot_decide(self):
        await self.join(self.player)
        [card] = self.cards()
        core_player = FakeMember(self.guild, "sv{member}", "sv{core-player}")

        for clicker in (core_player, self.player):
            with self.subTest(clicker=clicker.id):
                self.assertEqual(
                    await self.click(clicker, Decision.ACCEPT),
                    [(":no_entry: Only admins, managers and moderators can decide on this request.", True)],
                )
                self.assert_still_pending(card)

    async def test_a_click_on_a_handled_card_does_nothing(self):
        await self.join(self.player)
        [card] = self.cards()
        await self.click(self.moderator, Decision.DECLINE)
        handled = card.content

        self.assertEqual(
            await self.click(self.moderator, Decision.ACCEPT), [("This request was already handled.", True)]
        )

        self.assertEqual(card.content, handled)
        self.assertIsNone(store.player(self.ctf.id, self.player.id))
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_two_staff_clicking_at_once_only_the_first_decides(self):
        await self.join(self.player)
        [card] = self.cards()
        admin = FakeMember(self.guild, "sv{admin}")

        first, second = await asyncio.gather(
            self.click(self.moderator, Decision.ACCEPT), self.click(admin, Decision.DECLINE)
        )

        self.assertEqual((first, second), ([], [("This request was already handled.", True)]))
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.JOINED)
        self.assertEqual(self.player.dms, [])
        self.assertTrue(card.content.endswith(f"\n:white_check_mark: Accepted by <@{self.moderator.id}>"))

    async def test_a_card_whose_player_left_the_ctf_meanwhile_was_already_handled(self):
        await self.join(self.player)
        store.remove_player(self.ctf.id, self.player.id)

        self.assertEqual(
            await self.click(self.moderator, Decision.ACCEPT), [("This request was already handled.", True)]
        )
        self.assertNotIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_an_older_card_of_someone_asking_again_was_already_handled(self):
        await self.join(self.player)
        old = self.cards()[0]
        await self.click(self.moderator, Decision.DECLINE)
        await self.join(self.player)

        self.assertEqual(
            await self.click(self.moderator, Decision.ACCEPT, card=old), [("This request was already handled.", True)]
        )
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.PENDING)

    async def test_someone_who_left_the_server_cannot_be_accepted_but_can_be_declined(self):
        await self.join(self.player)
        [card] = self.cards()
        self.guild.members.remove(self.player)

        self.assertEqual(
            await self.click(self.moderator, Decision.ACCEPT),
            [(f"<@{self.player.id}> is no longer on the server, **Decline** to close this request.", True)],
        )
        self.assertEqual(store.player(self.ctf.id, self.player.id).status, PlayerStatus.PENDING)
        self.assertIsNotNone(card.view)

        await self.click(self.moderator, Decision.DECLINE)

        self.assertIsNone(store.player(self.ctf.id, self.player.id))
        self.assertTrue(card.content.endswith(f"\n:x: Declined by <@{self.moderator.id}> (left the server)"))

    async def test_accept_that_discord_refuses_leaves_the_request_open_to_try_again(self):
        await self.join(self.player)
        [card] = self.cards()
        asked = store.player(self.ctf.id, self.player.id)
        self.player.roles_fail = True

        with self.assertLogs("bot", "ERROR"):
            replies = await self.click(self.moderator, Decision.ACCEPT)

        self.assertEqual(replies, [("Sorry, an unknown error occurred, please ask a moderator for help.", True)])
        self.assertEqual(store.player(self.ctf.id, self.player.id), asked)
        self.assert_still_pending(card)

        self.player.roles_fail = False
        await self.click(self.moderator, Decision.ACCEPT)

        self.assertIn(self.guild.role("Foo CTF"), self.player.roles)

    async def test_decision_on_a_card_that_cannot_be_edited_is_told_to_the_clicker(self):
        await self.join(self.player)

        with self.assertLogs("bot", "ERROR"):
            replies = await self.click(self.moderator, Decision.DECLINE, edit_fails=True)

        self.assertEqual(
            replies, [(f":x: Declined by <@{self.moderator.id}>, but the card could not be updated.", True)]
        )
        self.assertIsNone(store.player(self.ctf.id, self.player.id))

    async def test_without_a_known_player_role_configured_the_card_has_no_known_player_button(self):
        self.settings = replace(SETTINGS, roles=replace(SETTINGS.roles, known_player=None))

        await self.join(self.player)

        self.assertEqual([label for label, _ in buttons(self.cards()[-1].view)], ["Accept", "Decline"])

    async def test_the_buttons_find_their_ctf_and_player_from_the_custom_id_after_a_restart(self):
        match = players.DecisionButton.__discord_ui_compiled_template__.fullmatch(
            f"ctf:card:known:{self.ctf.id}:{self.player.id}"
        )

        button = await players.DecisionButton.from_custom_id(None, None, match)

        self.assertEqual(
            (button.decision, button.ctf_id, button.user_id), (Decision.ACCEPT_KNOWN, self.ctf.id, self.player.id)
        )


if __name__ == "__main__":
    unittest.main()
