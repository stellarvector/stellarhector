import unittest

from ctf import credentials, store
from ctf.credentials import CredentialsRefused
from tests.factories import new_ctf, use_temporary_database, utc
from tests.fakes import FakeGuild

NOW = utc(2026, 10, 10, 8)


class PostCredentialsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.guild = FakeGuild()
        self.main = self.guild.channel("foo-ctf")
        ctf = store.create(new_ctf(main_channel_id=self.main.id, bot_channel_id=self.guild.channel("bot").id))
        self.ctf_id = ctf.id

    async def post(self, text):
        return await credentials.post_credentials(self.guild, store.reread(self.ctf_id), text)

    async def test_posts_the_credentials_pinned_in_the_main_channel(self):
        message = await self.post("user: team\npass: hunter2")

        self.assertEqual(self.main.messages, [message])
        self.assertEqual(message.content, "🔑 **Credentials**\nuser: team\npass: hunter2")
        self.assertTrue(message.pinned)
        self.assertEqual(store.reread(self.ctf_id).credentials_message_id, message.id)

    async def test_posting_again_replaces_the_earlier_credentials(self):
        await self.post("pass: wrong")

        message = await self.post("pass: right")

        self.assertEqual(self.main.messages, [message])
        self.assertEqual(store.reread(self.ctf_id).credentials_message_id, message.id)

    async def test_earlier_credentials_deleted_by_hand_are_replaced_too(self):
        await self.post("pass: wrong")
        self.main.messages.clear()

        message = await self.post("pass: right")

        self.assertEqual(self.main.messages, [message])

    async def test_refused_and_nothing_posted_when_the_earlier_credentials_cannot_be_deleted(self):
        earlier = await self.post("pass: wrong")
        self.main.delete_fails = True

        with self.assertRaisesRegex(CredentialsRefused, "earlier credentials"):
            await self.post("pass: right")

        self.assertEqual(self.main.messages, [earlier])
        self.assertEqual(store.reread(self.ctf_id).credentials_message_id, earlier.id)

    async def test_refused_once_the_ctf_is_released_or_locked(self):
        for mark in (store.mark_released, store.mark_locked):
            with self.subTest(mark.__name__):
                mark(self.ctf_id, NOW)

                with self.assertRaisesRegex(CredentialsRefused, "visible to all members"):
                    await self.post("pass: hunter2")

                self.assertEqual(self.main.messages, [])

    async def test_refused_when_the_main_channel_is_gone(self):
        self.guild.channels.remove(self.main)

        with self.assertRaisesRegex(CredentialsRefused, "main channel"):
            await self.post("pass: hunter2")


class CurrentCredentialsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.guild = FakeGuild()
        self.main = self.guild.channel("foo-ctf")
        self.ctf_id = store.create(new_ctf(main_channel_id=self.main.id)).id

    async def current(self):
        return await credentials.current_credentials(self.guild, store.reread(self.ctf_id))

    async def test_is_the_posted_text_without_its_header(self):
        await credentials.post_credentials(self.guild, store.reread(self.ctf_id), "user: team\npass: hunter2")

        self.assertEqual(await self.current(), "user: team\npass: hunter2")

    async def test_is_none_without_credentials(self):
        self.assertIsNone(await self.current())

    async def test_is_none_when_the_credentials_were_deleted_by_hand(self):
        await credentials.post_credentials(self.guild, store.reread(self.ctf_id), "pass: hunter2")
        self.main.messages.clear()

        self.assertIsNone(await self.current())


if __name__ == "__main__":
    unittest.main()
