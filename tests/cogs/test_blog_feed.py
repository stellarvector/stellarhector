import unittest
from types import SimpleNamespace
from unittest import mock

from cogs.blog_feed import BlogFeed, BlogPostsFailed, check_reply
from feeds.blog import BlogCheckResult
from tests.factories import SETTINGS


class CheckReplyTest(unittest.TestCase):
    def test_reply_counts_the_created_posts(self):
        self.assertEqual(
            check_reply(BlogCheckResult(created=2)), ":white_check_mark: Blog checked: 2 forum posts created."
        )

    def test_reply_mentions_posts_that_could_not_be_created(self):
        self.assertEqual(
            check_reply(BlogCheckResult(created=1, failed=1)),
            ":warning: Blog checked: 1 forum post created. 1 could not be created; it is tried again on"
            " the next check.",
        )

    def test_reply_after_the_first_check(self):
        self.assertEqual(
            check_reply(BlogCheckResult(recorded=13)),
            ":white_check_mark: First blog check: the 13 current posts were recorded without posting them."
            " New posts get a forum post from now on.",
        )

    def test_reply_after_a_first_check_with_one_post(self):
        self.assertEqual(
            check_reply(BlogCheckResult(recorded=1)),
            ":white_check_mark: First blog check: the 1 current post was recorded without posting it."
            " New posts get a forum post from now on.",
        )


class ScheduledCheckTest(unittest.IsolatedAsyncioTestCase):
    """A scheduled check fails, so the scheduler alerts, when it had new posts and could post none of them."""

    async def scheduled_check(self, result):
        cog = BlogFeed(SimpleNamespace(settings=SETTINGS))
        with mock.patch.object(cog, "check_blog", return_value=result):
            await cog.scheduled_check()

    async def test_posting_none_of_the_new_posts_fails(self):
        with self.assertRaisesRegex(BlogPostsFailed, "None of the 2 new blog posts could be posted"):
            await self.scheduled_check(BlogCheckResult(failed=2))

    async def test_posting_some_of_the_new_posts_works(self):
        await self.scheduled_check(BlogCheckResult(created=1, failed=2))

    async def test_a_check_without_new_posts_works(self):
        await self.scheduled_check(BlogCheckResult())
        await self.scheduled_check(BlogCheckResult(recorded=13))


if __name__ == "__main__":
    unittest.main()
