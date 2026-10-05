"""New posts on Stellar Vector's blog, shared as forum posts in #learning."""

import html
import logging
import xml.etree.ElementTree as ElementTree
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from urllib.parse import urlparse

import aiohttp
import discord

import core.db as db
from feeds import FeedError
from utils.text import cut
from utils.unfinished import UnfinishedWork

log = logging.getLogger("bot")

FEED_URL = "https://blog.stellarvector.be/index.xml"
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Discord's limits for the title of a forum post and the message opening it
TITLE_LIMIT = 100
MESSAGE_LIMIT = 2000

# The forum tags blog posts get, looked up by name ignoring case
WRITEUP_TAG = "writeup"
TEAM_TAG = "Stellar Vector"

NO_TITLE = "Untitled post"


# The posts and records of checks that were stopped halfway
_unfinished = UnfinishedWork()

# Creates a forum post from its title, body and tag names
CreatePost = Callable[[str, str, list[str]], Awaitable[None]]
Fetch = Callable[[], Awaitable[bytes]]


@dataclass(frozen=True)
class Post:
    """One item of the blog feed. `ctf` is the item's <category domain="ctf">. The description has its HTML entities
    decoded, as Hugo escapes them once more on top of the XML escaping."""

    guid: str
    title: str
    link: str
    description: str | None
    ctf: str | None


@dataclass(frozen=True)
class BlogCheckResult:
    created: int = 0
    # Forum posts that could not be created; they are tried again on the next check
    failed: int = 0
    # Items the very first check recorded without posting them
    recorded: int = 0


async def download() -> bytes:
    try:
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
            async with session.get(FEED_URL) as response:
                response.raise_for_status()
                return await response.read()
    except (TimeoutError, aiohttp.ClientError) as e:
        raise FeedError(f"Blog feed could not be downloaded: {e!r}") from e


async def check(create_post: CreatePost, fetch: Fetch = download) -> BlogCheckResult:
    """Create a forum post through `create_post` for every feed item that was not seen before, oldest first. The very
    first check, when nothing was seen yet, only records the current items, so the blog's history is not posted.

    Raises FeedError before anything changes when the feed can't be downloaded or parsed. A forum post that can't be
    created is logged, and its item is tried again on the next check.
    """
    # A check that was stopped may still be posting and recording; wait for it, so it is not posted again
    await _unfinished.wait()

    posts = parse_feed(await fetch())
    seen = _seen()
    if not seen:
        _record([post.guid for post in posts])
        return BlogCheckResult(recorded=len({post.guid for post in posts}))

    result = BlogCheckResult()
    # The feed lists the newest item first
    for post in reversed(posts):
        if post.guid in seen:
            continue
        seen.add(post.guid)

        # Shielded: when the check is stopped mid-post, a created post is still recorded so it is not posted twice
        if await _unfinished.finish_even_if_stopped(_post_and_record(post, create_post)):
            result = replace(result, created=result.created + 1)
        else:
            result = replace(result, failed=result.failed + 1)
    return result


def parse_feed(xml: bytes) -> list[Post]:
    """The posts in feed order. Raises FeedError when `xml` is not an RSS feed."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise FeedError(f"Blog feed is not valid XML: {e}") from e
    channel = root.find("channel")
    if root.tag != "rss" or channel is None:
        raise FeedError(f"Blog feed is not an RSS feed, its root is <{root.tag}>")

    posts = []
    for item in channel.iter("item"):
        post = _post(item)
        if post is None:
            log.warning(f"Blog feed item without a guid or link skipped: {_text(item, 'title')!r}")
        else:
            posts.append(post)
    return posts


def is_writeup(post: Post) -> bool:
    return _path(post.link)[:1] == ["writeups"]


def forum_title(post: Post) -> str:
    if not is_writeup(post):
        return cut(f"[SV blog] {post.title}", TITLE_LIMIT)

    ctf = ctf_name(post)
    return cut(f"[SV writeup] {post.title}" if ctf is None else f"[SV writeup] {ctf} / {post.title}", TITLE_LIMIT)


def forum_body(post: Post) -> str:
    """What the post is, its description when it has one, and its link."""
    heading = "New writeup on Stellar Vector's blog" if is_writeup(post) else "New post on Stellar Vector's blog"
    if post.description is None:
        return f"{heading}\n\n{post.link}"

    room = MESSAGE_LIMIT - len(f"{heading}\n\n\n\n{post.link}")
    description = cut(discord.utils.escape_markdown(post.description), room)
    return f"{heading}\n\n{description}\n\n{post.link}"


def tag_names(post: Post) -> list[str]:
    return [WRITEUP_TAG, TEAM_TAG] if is_writeup(post) else [TEAM_TAG]


def find_tags(available: Iterable[discord.ForumTag], names: list[str]) -> list[discord.ForumTag]:
    """The forum's tags with `names`, ignoring case, in the order of `names`. A name the forum has no tag for is
    skipped with a warning; tags are never created."""
    by_name = {tag.name.casefold(): tag for tag in available}
    found = []
    for name in names:
        tag = by_name.get(name.casefold())
        if tag is None:
            log.warning(f"The #learning forum has no {name!r} tag, the blog post goes without it")
        else:
            found.append(tag)
    return found


def ctf_name(post: Post) -> str | None:
    """The name of the CTF a writeup is about: its ctf category, else the CTF slug in its link
    (/writeups/<year>/<ctf-slug>/...) in title case."""
    if post.ctf is not None:
        return post.ctf

    path = _path(post.link)
    if len(path) < 3:
        return None
    return path[2].replace("-", " ").title()


def _path(link: str) -> list[str]:
    return [segment for segment in urlparse(link).path.split("/") if segment]


def _post(item: ElementTree.Element) -> Post | None:
    """None when the item has no link."""
    link = _text(item, "link")
    guid = _text(item, "guid") or link
    if guid is None or link is None:
        return None

    ctf = next((category.text for category in item.iter("category") if category.get("domain") == "ctf"), None)
    description = _stripped(html.unescape(item.findtext("description") or ""))
    return Post(
        guid=guid, title=_text(item, "title") or NO_TITLE, link=link, description=description, ctf=_stripped(ctf)
    )


def _text(item: ElementTree.Element, tag: str) -> str | None:
    return _stripped(item.findtext(tag))


def _stripped(text: str | None) -> str | None:
    """`text` without surrounding whitespace, or None when that leaves nothing."""
    return (text or "").strip() or None


async def _post_and_record(post: Post, create_post: CreatePost) -> bool:
    """Returns whether the forum post was created."""
    try:
        await create_post(forum_title(post), forum_body(post), tag_names(post))
    except Exception:
        log.exception(f"Could not create the forum post for blog post {post.link}")
        return False
    _record([post.guid])
    return True


def _seen() -> set[str]:
    with db.transaction() as conn:
        return {row["guid"] for row in conn.execute("SELECT guid FROM blog_posts_seen")}


def _record(guids: Iterable[str]) -> None:
    now = db.time_text(datetime.now(UTC))
    with db.transaction() as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO blog_posts_seen (guid, seen_at) VALUES (?, ?)", [(guid, now) for guid in guids]
        )
