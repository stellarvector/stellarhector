import asyncio
import tempfile
import unittest
from pathlib import Path

from core import db
from utils import blog_feed
from utils.blog_feed import Post

FIXTURES = Path(__file__).parent / "fixtures" / "blog"


def load(name):
    return (FIXTURES / name).read_text()


WRITEUP = "https://blog.stellarvector.be/writeups/2023/hackthebox-university-ctf-brains-bytes/gatecrash/"


def item(link=WRITEUP, title="GateCrash", description="Nim CRLF injection.", categories="", guid=None):
    description = "" if description is None else f"<description>{description}</description>"
    return (f"<item><title>{title}</title><link>{link}</link><guid>{guid or link}</guid>{description}{categories}"
            f"</item>")


def feed(*items):
    return f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>{"".join(items)}</channel></rss>'


class ParseFeedTest(unittest.TestCase):
    def test_parses_every_item_of_the_stored_feed(self):
        posts = blog_feed.parse_feed(load("index.xml"))

        self.assertEqual(len(posts), 13)
        self.assertEqual(posts[1], Post(
            guid="https://blog.stellarvector.be/writeups/2023/hackthebox-university-ctf-brains-bytes/gatecrash/",
            title="GateCrash",
            link="https://blog.stellarvector.be/writeups/2023/hackthebox-university-ctf-brains-bytes/gatecrash/",
            description="Deep dive into Nim-specific CRLF injection (CVE-2020-15693). Shows how to inject JSON payloads"
                        " into headers to bypass frontend filters and achieve SQL injection.",
            ctf=None,
        ))

    def test_reads_the_ctf_category(self):
        posts = blog_feed.parse_feed(feed(item(categories='<category>crypto</category>'
                                                          '<category domain="ctf">HTB University CTF 2023</category>')))

        self.assertEqual(posts[0].ctf, "HTB University CTF 2023")

    def test_html_entities_in_the_description_are_decoded(self):
        posts = blog_feed.parse_feed(feed(item(description="the site&amp;rsquo;s &amp;lsquo;magic&amp;rsquo; &amp;amp; more")))

        self.assertEqual(posts[0].description, "the site’s ‘magic’ & more")

    def test_item_without_a_description_has_none(self):
        posts = blog_feed.parse_feed(feed(item(description=None)))

        self.assertIsNone(posts[0].description)

    def test_item_without_a_guid_is_known_by_its_link(self):
        posts = blog_feed.parse_feed(feed(item().replace(f"<guid>{WRITEUP}</guid>", "")))

        self.assertEqual(posts[0].guid, WRITEUP)

    def test_item_without_a_guid_or_link_is_skipped(self):
        with self.assertLogs("bot", level="WARNING"):
            posts = blog_feed.parse_feed(feed(item(link="", guid=" "), item()))

        self.assertEqual([post.guid for post in posts], [WRITEUP])

    def test_feed_that_is_not_xml_is_a_feed_error(self):
        with self.assertRaises(blog_feed.FeedError):
            blog_feed.parse_feed("<html><body>502 Bad Gateway")

    def test_xml_that_is_not_an_rss_feed_is_a_feed_error(self):
        with self.assertRaises(blog_feed.FeedError):
            blog_feed.parse_feed("<html><body>Not found</body></html>")


def post(link=WRITEUP, title="GateCrash", description="Nim CRLF injection.", ctf=None):
    return Post(guid=link, title=title, link=link, description=description, ctf=ctf)


class TitleTest(unittest.TestCase):
    def test_writeup_title_names_the_ctf_from_the_link(self):
        self.assertEqual(blog_feed.forum_title(post()),
                         "[SV writeup] Hackthebox University Ctf Brains Bytes / GateCrash")

    def test_ctf_category_overrides_the_ctf_from_the_link(self):
        self.assertEqual(blog_feed.forum_title(post(ctf="HTB University CTF 2023")),
                         "[SV writeup] HTB University CTF 2023 / GateCrash")

    def test_other_post_title(self):
        self.assertEqual(blog_feed.forum_title(post(link="https://blog.stellarvector.be/posts/welcome/", title="Welcome")),
                         "[SV blog] Welcome")

    def test_long_title_is_cut_to_discords_limit(self):
        title = blog_feed.forum_title(post(title="x" * 200))

        self.assertEqual(len(title), 100)
        self.assertTrue(title.startswith("[SV writeup] Hackthebox University Ctf Brains Bytes / xxx"))
        self.assertTrue(title.endswith("x…"))


OTHER = "https://blog.stellarvector.be/posts/welcome/"


class BodyTest(unittest.TestCase):
    def test_writeup_body(self):
        self.assertEqual(blog_feed.forum_body(post()),
                         f"New writeup on Stellar Vector's blog\n\nNim CRLF injection.\n\n{WRITEUP}")

    def test_other_post_body(self):
        self.assertEqual(blog_feed.forum_body(post(link=OTHER)),
                         f"New post on Stellar Vector's blog\n\nNim CRLF injection.\n\n{OTHER}")

    def test_body_without_a_description(self):
        self.assertEqual(blog_feed.forum_body(post(description=None)),
                         f"New writeup on Stellar Vector's blog\n\n{WRITEUP}")

    def test_description_shows_as_typed(self):
        body = blog_feed.forum_body(post(description="Use *args and __init__"))

        self.assertIn(r"Use \*args and \_\_init\_\_", body)

    def test_long_description_is_cut_to_fit_one_discord_message(self):
        body = blog_feed.forum_body(post(description="*" * 3000))

        self.assertLessEqual(len(body), 2000)
        self.assertTrue(body.endswith(f"…\n\n{WRITEUP}"))


class FakeTag:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"FakeTag({self.name!r})"


class TagsTest(unittest.TestCase):
    def test_writeup_has_the_writeup_and_stellar_vector_tags(self):
        self.assertEqual(blog_feed.tag_names(post()), ["writeup", "Stellar Vector"])

    def test_other_post_has_only_the_stellar_vector_tag(self):
        self.assertEqual(blog_feed.tag_names(post(link=OTHER)), ["Stellar Vector"])

    def test_tags_are_found_on_the_forum_ignoring_case(self):
        writeup, team, other = FakeTag("Writeup"), FakeTag("stellar vector"), FakeTag("crypto")

        found = blog_feed.find_tags([other, team, writeup], ["writeup", "Stellar Vector"])

        self.assertEqual(found, [writeup, team])

    def test_tag_missing_on_the_forum_is_skipped_with_a_warning(self):
        team = FakeTag("Stellar Vector")

        with self.assertLogs("bot", level="WARNING") as logs:
            found = blog_feed.find_tags([team], ["writeup", "Stellar Vector"])

        self.assertEqual(found, [team])
        self.assertIn("writeup", logs.output[0])


class ReplyTest(unittest.TestCase):
    def test_reply_counts_the_created_posts(self):
        self.assertEqual(blog_feed.reply(blog_feed.CheckResult(created=2)),
                         ":white_check_mark: Blog checked: 2 forum posts created.")

    def test_reply_mentions_posts_that_could_not_be_created(self):
        self.assertEqual(blog_feed.reply(blog_feed.CheckResult(created=1, failed=1)),
                         ":warning: Blog checked: 1 forum post created. 1 could not be created; it is tried again on"
                         " the next check.")

    def test_reply_after_the_first_check(self):
        self.assertEqual(blog_feed.reply(blog_feed.CheckResult(recorded=13)),
                         ":white_check_mark: First blog check: the 13 current posts were recorded without posting them."
                         " New posts get a forum post from now on.")

    def test_reply_after_a_first_check_with_one_post(self):
        self.assertEqual(blog_feed.reply(blog_feed.CheckResult(recorded=1)),
                         ":white_check_mark: First blog check: the 1 current post was recorded without posting it."
                         " New posts get a forum post from now on.")

    def test_skipped_reply_shows_the_error(self):
        self.assertEqual(blog_feed.skipped_reply(blog_feed.FeedError("Blog feed is not valid XML")),
                         ":warning: The blog feed could not be read, so nothing changed: `Blog feed is not valid XML`")


def use_temporary_database(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    db.init(Path(tmp.name) / "test.db")
    test.addCleanup(db.close)


class FakeFeed:
    """Stands in for downloading the feed: answers with xml, or raises FeedError when xml is None."""

    def __init__(self, xml):
        self.xml = xml

    async def __call__(self):
        if self.xml is None:
            raise blog_feed.FeedError("blog.stellarvector.be is down")
        return self.xml


NEW = "https://blog.stellarvector.be/writeups/2026/lakectf/new-challenge/"


class CheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.created = []
        self.failing = set()

    async def create_post(self, title, body, tags):
        if title in self.failing:
            raise RuntimeError("Discord is down")
        self.created.append((title, body, tags))

    async def check(self, xml):
        return await blog_feed.check(self.create_post, fetch=FakeFeed(xml))

    async def test_first_check_posts_nothing_and_records_every_item(self):
        first = await self.check(load("index.xml"))
        second = await self.check(load("index.xml"))

        self.assertEqual(self.created, [])
        self.assertEqual(first, blog_feed.CheckResult(created=0, recorded=13))
        self.assertEqual(second, blog_feed.CheckResult())

    async def test_new_writeup_creates_one_forum_post(self):
        await self.check(feed(item()))

        result = await self.check(feed(item(link=NEW, title="new-challenge", description="Fresh."), item()))

        self.assertEqual(result, blog_feed.CheckResult(created=1))
        self.assertEqual(self.created, [("[SV writeup] Lakectf / new-challenge",
                                         f"New writeup on Stellar Vector's blog\n\nFresh.\n\n{NEW}",
                                         ["writeup", "Stellar Vector"])])

    async def test_running_the_check_twice_posts_an_item_once(self):
        await self.check(feed(item()))
        new_feed = feed(item(link=NEW), item())

        await self.check(new_feed)
        await self.check(new_feed)

        self.assertEqual(len(self.created), 1)

    async def test_several_new_items_are_posted_oldest_first(self):
        await self.check(feed(item()))

        await self.check(feed(item(link=OTHER, title="Newest"), item(link=NEW, title="Older"), item()))

        self.assertEqual([title for title, _, _ in self.created], ["[SV writeup] Lakectf / Older", "[SV blog] Newest"])

    async def test_feed_that_cannot_be_read_changes_nothing(self):
        with self.assertRaises(blog_feed.FeedError):
            await self.check(None)
        with self.assertRaises(blog_feed.FeedError):
            await self.check("<html>")

        first = await self.check(feed(item()))

        self.assertEqual((first, self.created), (blog_feed.CheckResult(recorded=1), []))

    async def test_post_that_could_not_be_created_is_tried_again_on_the_next_check(self):
        await self.check(feed(item()))
        new_feed = feed(item(link=OTHER, title="Fine"), item(link=NEW, title="Broken"), item())
        self.failing = {"[SV writeup] Lakectf / Broken"}

        with self.assertLogs("bot", level="ERROR"):
            failed = await self.check(new_feed)
        self.failing = set()
        retried = await self.check(new_feed)

        self.assertEqual((failed, retried), (blog_feed.CheckResult(created=1, failed=1), blog_feed.CheckResult(created=1)))
        self.assertEqual([title for title, _, _ in self.created], ["[SV blog] Fine", "[SV writeup] Lakectf / Broken"])

    async def test_check_stopped_while_posting_is_not_posted_again_by_the_next_check(self):
        await self.check(feed(item()))
        new_feed = feed(item(link=NEW), item())
        posting = asyncio.Event()
        release = asyncio.Event()

        async def slow_create_post(title, body, tags):
            posting.set()
            await release.wait()
            self.created.append((title, body, tags))

        stopped = asyncio.create_task(blog_feed.check(slow_create_post, fetch=FakeFeed(new_feed)))
        await posting.wait()
        stopped.cancel()
        next_check = asyncio.create_task(self.check(new_feed))
        await asyncio.sleep(0)
        release.set()
        await next_check

        self.assertEqual(len(self.created), 1)


if __name__ == "__main__":
    unittest.main()
