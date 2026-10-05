import unittest
from dataclasses import replace

import discord

from cogs import players
from ctf import join_message, store
from ctf.models import NewCtf
from tests.factories import use_temporary_database, utc
from tests.fakes import FakeChannel, FakeGuild, FakeInteraction, FakeMember, FakeMessage, buttons, http_error

NOW = utc(2026, 10, 9, 8)


class LastCallTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.guild = FakeGuild()
        self.upcoming = self.guild.channel("upcoming-ctfs")
        ctf = store.create(
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
        self.upcoming.messages.append(self.join_message)
        store.set_join_message(ctf.id, self.upcoming.id, self.join_message.id)

        self.player = FakeMember(self.guild, "sv{member}", "sv{core-player}")
        store.add_player(ctf.id, self.player.id, utc(2026, 10, 1, 12))
        self.ctf = store.get(ctf.id)

    async def last_call(self, ctf=None, channel_id=None):
        return await join_message.post_last_call(self.guild, ctf or self.ctf, channel_id or self.upcoming.id, NOW)

    async def test_reposts_the_join_message_at_the_bottom_as_last_call_with_the_same_players(self):
        self.upcoming.messages.append(FakeMessage("someone else's message"))

        ctf = await self.last_call()

        self.assertNotIn(self.join_message, self.upcoming.messages)
        new = self.upcoming.messages[-1]
        self.assertEqual(new.content, f"## :rotating_light: Last call: Foo CTF\n**Playing (1):** <@{self.player.id}>")
        self.assertEqual(buttons(new.view), [("Join", f"ctf:join:{self.ctf.id}")])
        self.assertEqual(ctf, store.get(self.ctf.id))
        self.assertEqual((ctf.join_channel_id, ctf.join_message_id, ctf.last_call_at), (self.upcoming.id, new.id, NOW))

    async def test_joining_on_the_new_message_shows_the_player_on_it(self):
        await self.last_call()
        newcomer = FakeMember(self.guild, "sv{member}", "sv{known-player}")

        interaction = FakeInteraction(newcomer, self.guild, f"ctf:join:{self.ctf.id}")
        await players.JoinButton(self.ctf.id).callback(interaction)

        self.assertIn(self.guild.role("Foo CTF"), newcomer.roles)
        self.assertEqual(
            self.upcoming.messages[-1].content,
            f"## :rotating_light: Last call: Foo CTF\n**Playing (2):** <@{self.player.id}>, <@{newcomer.id}>",
        )

    async def test_refreshing_with_the_ctf_as_it_was_before_the_last_call_updates_the_new_message(self):
        before = self.ctf
        await self.last_call()
        store.remove_player(self.ctf.id, self.player.id)

        await join_message.refresh_join_message(self.guild, before)

        self.assertEqual(
            self.upcoming.messages[-1].content,
            "## :rotating_light: Last call: Foo CTF\n**Playing:** nobody yet, click **Join** to be the first",
        )

    async def test_refused_once_joining_is_closed(self):
        for step in ("released_at", "locked_at"):
            with self.subTest(step):
                with self.assertRaisesRegex(join_message.LastCallRefused, r"Joining \*\*Foo CTF\*\* is closed"):
                    await self.last_call(replace(self.ctf, **{step: utc(2026, 10, 8, 8)}))

                self.assertEqual(self.upcoming.messages, [self.join_message])
                self.assertIsNone(store.get(self.ctf.id).last_call_at)

    async def test_refused_when_joining_closed_since_the_ctf_was_read(self):
        store.mark_released(self.ctf.id, utc(2026, 10, 8, 8))

        with self.assertRaises(join_message.LastCallRefused):
            await self.last_call()

        self.assertEqual(self.upcoming.messages, [self.join_message])

    async def test_refreshing_a_ctf_that_was_deleted_meanwhile_does_nothing(self):
        store.delete(self.ctf.id)

        await join_message.refresh_join_message(self.guild, self.ctf)

        self.assertEqual(self.join_message.content, "join message")

    async def test_join_message_deleted_by_hand_is_posted_again_all_the_same(self):
        self.upcoming.messages.remove(self.join_message)

        ctf = await self.last_call()

        [new] = self.upcoming.messages
        self.assertEqual(ctf.join_message_id, new.id)

    async def test_a_second_last_call_moves_it_to_the_bottom_again(self):
        first = await self.last_call()
        self.upcoming.messages.append(FakeMessage("someone else's message"))

        second = await self.last_call(first)

        self.assertEqual([message.id for message in self.upcoming.messages][-1], second.join_message_id)
        self.assertEqual(len(self.upcoming.messages), 2)

    async def test_ctf_without_a_join_message_gets_one(self):
        store.set_join_message(self.ctf.id, None, None)
        self.upcoming.messages.remove(self.join_message)

        ctf = await self.last_call(store.get(self.ctf.id))

        [new] = self.upcoming.messages
        self.assertEqual((ctf.join_channel_id, ctf.join_message_id), (self.upcoming.id, new.id))

    async def test_join_message_in_an_old_channel_is_deleted_there_and_posted_in_the_current_one(self):
        current = FakeChannel("new-upcoming-ctfs")
        self.guild.channels.append(current)

        ctf = await self.last_call(channel_id=current.id)

        self.assertEqual(self.upcoming.messages, [])
        [new] = current.messages
        self.assertEqual((ctf.join_channel_id, ctf.join_message_id), (current.id, new.id))

    async def test_refused_when_upcoming_ctfs_does_not_exist(self):
        with self.assertRaisesRegex(join_message.LastCallRefused, "#upcoming-ctfs"):
            await self.last_call(channel_id=12345)

        self.assertEqual(self.upcoming.messages, [self.join_message])

    async def test_old_message_that_cannot_be_deleted_is_logged_and_the_new_one_stands(self):
        async def refuse():
            raise http_error(discord.HTTPException, 500)

        original = self.upcoming.get_partial_message

        def partial(message_id):
            message = original(message_id)
            message.delete = refuse
            return message

        self.upcoming.get_partial_message = partial

        with self.assertLogs("bot", "ERROR"):
            ctf = await self.last_call()

        self.assertEqual(ctf.join_message_id, self.upcoming.messages[-1].id)


if __name__ == "__main__":
    unittest.main()
