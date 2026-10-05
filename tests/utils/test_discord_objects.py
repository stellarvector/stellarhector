import unittest
from types import SimpleNamespace
from unittest import mock

import discord

from utils.discord_objects import all_threads


async def threads(*found):
    for thread in found:
        yield thread


class AllThreadsTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_text_channel_has_its_active_and_archived_public_and_private_threads(self):
        active, archived_public, archived_private = SimpleNamespace(id=3), SimpleNamespace(id=1), SimpleNamespace(id=2)
        channel = SimpleNamespace(
            threads=[active],
            archived_threads=lambda private, limit: threads(archived_private if private else archived_public),
        )

        self.assertEqual(await all_threads(channel), [archived_public, archived_private, active])

    async def test_a_forum_is_not_asked_for_private_threads_it_cannot_have(self):
        forum = mock.MagicMock(spec=discord.ForumChannel)
        post, old_post = SimpleNamespace(id=2), SimpleNamespace(id=1)
        forum.threads = [post]
        forum.archived_threads = lambda limit: threads(old_post)

        self.assertEqual(await all_threads(forum), [old_post, post])

    async def test_a_channel_without_threads_has_none(self):
        self.assertEqual(await all_threads(SimpleNamespace()), [])


if __name__ == "__main__":
    unittest.main()
