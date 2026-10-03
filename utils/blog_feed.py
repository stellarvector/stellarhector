"""Shares the new posts of Stellar Vector's blog as forum posts in #learning.

parse_feed and the forum post builders are pure. check downloads the feed and creates a forum post for every item it
has not seen before.
"""
import asyncio
import html
import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from urllib.parse import urlparse

import aiohttp
import discord

import core.db as db
from utils.text import cut, inline_code

FEED_URL = "https://blog.stellarvector.be/index.xml"
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Discord's limits for the title of a forum post and the message opening it
TITLE_LIMIT = 100
MESSAGE_LIMIT = 2000

# The forum tags blog posts get, looked up by name ignoring case
WRITEUP_TAG = "writeup"
TEAM_TAG = "Stellar Vector"

NO_TITLE = "Untitled post"

# How much of the reason a skipped /blog-check reply shows
REASON_LIMIT = 500

# The post-and-record work of checks that were stopped while it ran
_unfinished = set()


class FeedError(Exception):
    """The blog feed could not be downloaded or is not an RSS feed."""


@dataclass(frozen=True)
class Post:
    """One item of the blog feed. ctf is the item's <category domain="ctf">, None when it has none. The description
    has its HTML entities decoded: Hugo escapes them once more on top of the XML escaping."""
    guid: str
    title: str
    link: str
    description: str | None
    ctf: str | None


@dataclass(frozen=True)
class CheckResult:
    """What one check did: how many forum posts it created, how many it could not create (they are tried again on the
    next check), and how many items the very first check recorded without posting them."""
    created: int = 0
    failed: int = 0
    recorded: int = 0


async def download():
    """The blog feed as bytes. Raises FeedError when it can't be downloaded."""
    try:
        async with aiohttp.ClientSession(timeout=DOWNLOAD_TIMEOUT) as session:
            async with session.get(FEED_URL) as response:
                response.raise_for_status()
                return await response.read()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise FeedError(f"Blog feed could not be downloaded: {e!r}") from e


async def check(create_post, fetch=download):
    """Download the feed and create a forum post through create_post(title, body, tag_names) for every item that was
    not seen before, oldest first. The very first check (nothing seen yet) only records the current items, so the
    blog's history is not posted. Returns a CheckResult.

    Raises FeedError, before anything changes, when the feed can't be downloaded or parsed. A forum post that can't
    be created is logged, and its item is tried again on the next check.
    """
    # A check that was stopped may still be posting and recording; wait for it, so it is not posted again
    if _unfinished:
        await asyncio.wait(_unfinished)

    posts = parse_feed(await fetch())
    seen = _seen()
    if not seen:
        _record([post.guid for post in posts])
        return CheckResult(recorded=len({post.guid for post in posts}))

    result = CheckResult()
    # The feed lists the newest item first
    for post in reversed(posts):
        if post.guid in seen:
            continue
        seen.add(post.guid)

        # Shielded: when the check is stopped mid-post, a created post is still recorded so it is not posted twice
        posting = asyncio.ensure_future(_post_and_record(post, create_post))
        _unfinished.add(posting)
        posting.add_done_callback(_unfinished.discard)
        if await asyncio.shield(posting):
            result = replace(result, created=result.created + 1)
        else:
            result = replace(result, failed=result.failed + 1)
    return result


def reply(result):
    """The /blog-check reply after a check."""
    if result.recorded:
        was, them = ("was", "it") if result.recorded == 1 else ("were", "them")
        return (f":white_check_mark: First blog check: the {_count(result.recorded, 'current post')} {was} recorded"
                f" without posting {them}. New posts get a forum post from now on.")

    text = f"Blog checked: {_count(result.created, 'forum post')} created."
    if not result.failed:
        return f":white_check_mark: {text}"
    return (f":warning: {text} {result.failed} could not be created;"
            f" {'it is' if result.failed == 1 else 'they are'} tried again on the next check.")


def skipped_reply(error):
    """The /blog-check reply when the check was skipped because of the FeedError error."""
    return f":warning: The blog feed could not be read, so nothing changed: {inline_code(str(error), REASON_LIMIT)}"


def _count(number, noun):
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def parse_feed(xml):
    """The Posts in the RSS feed xml, in feed order. Raises FeedError when xml is not an RSS feed."""
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as e:
        raise FeedError(f"Blog feed is not valid XML: {e}") from e
    if root.tag != "rss" or root.find("channel") is None:
        raise FeedError(f"Blog feed is not an RSS feed, its root is <{root.tag}>")

    posts = []
    for item in root.find("channel").iter("item"):
        post = _post(item)
        if post is None:
            logging.getLogger("bot").warning(f"Blog feed item without a guid or link skipped: {_text(item, 'title')!r}")
        else:
            posts.append(post)
    return posts


def is_writeup(post):
    """Whether post is a writeup: its link is under /writeups/."""
    return _path(post.link)[:1] == ["writeups"]


def forum_title(post):
    """The title of post's forum post, cut to Discord's limit."""
    if not is_writeup(post):
        return cut(f"[SV blog] {post.title}", TITLE_LIMIT)

    ctf = ctf_name(post)
    return cut(f"[SV writeup] {post.title}" if ctf is None else f"[SV writeup] {ctf} / {post.title}", TITLE_LIMIT)


def forum_body(post):
    """The message opening post's forum post: what it is, the description (when it has one) and the link."""
    heading = "New writeup on Stellar Vector's blog" if is_writeup(post) else "New post on Stellar Vector's blog"
    if post.description is None:
        return f"{heading}\n\n{post.link}"

    room = MESSAGE_LIMIT - len(f"{heading}\n\n\n\n{post.link}")
    description = cut(discord.utils.escape_markdown(post.description), room)
    return f"{heading}\n\n{description}\n\n{post.link}"


def tag_names(post):
    """The names of the forum tags post's forum post gets."""
    return [WRITEUP_TAG, TEAM_TAG] if is_writeup(post) else [TEAM_TAG]


def find_tags(available, names):
    """The tags among available (the forum's tags) with the given names, ignoring case, in the order of names. A name
    the forum has no tag for is skipped with a warning; tags are never created."""
    by_name = {tag.name.casefold(): tag for tag in available}
    found = []
    for name in names:
        tag = by_name.get(name.casefold())
        if tag is None:
            logging.getLogger("bot").warning(f"The #learning forum has no {name!r} tag, the blog post goes without it")
        else:
            found.append(tag)
    return found


def ctf_name(post):
    """The name of the CTF the writeup post is about: its ctf category, else the CTF slug in its link
    (/writeups/<year>/<ctf-slug>/...) in title case. None when it has neither."""
    if post.ctf is not None:
        return post.ctf

    path = _path(post.link)
    if len(path) < 3:
        return None
    return path[2].replace("-", " ").title()


def _path(link):
    """The segments of link's path."""
    return [segment for segment in urlparse(link).path.split("/") if segment]


def _post(item):
    """The Post of the feed item, None when it has nothing to know it by."""
    link = _text(item, "link")
    guid = _text(item, "guid") or link
    if guid is None or link is None:
        return None

    ctf = next((category.text for category in item.iter("category") if category.get("domain") == "ctf"), None)
    description = _stripped(html.unescape(item.findtext("description") or ""))
    return Post(guid=guid, title=_text(item, "title") or NO_TITLE, link=link, description=description,
                ctf=_stripped(ctf))


def _text(item, tag):
    return _stripped(item.findtext(tag))


def _stripped(text):
    """text without surrounding whitespace, None when that leaves nothing."""
    return (text or "").strip() or None


async def _post_and_record(post, create_post):
    """Create post's forum post and record its item as seen. Returns whether the forum post was created."""
    try:
        await create_post(forum_title(post), forum_body(post), tag_names(post))
    except Exception:
        logging.getLogger("bot").exception(f"Could not create the forum post for blog post {post.link}")
        return False
    _record([post.guid])
    return True


def _seen():
    with db.transaction() as conn:
        return {row["guid"] for row in conn.execute("SELECT guid FROM blog_posts_seen")}


def _record(guids):
    now = db.time_text(datetime.now(timezone.utc))
    with db.transaction() as conn:
        conn.executemany("INSERT OR IGNORE INTO blog_posts_seen (guid, seen_at) VALUES (?, ?)",
                         [(guid, now) for guid in guids])
