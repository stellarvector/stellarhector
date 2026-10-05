"""Shares every new post on Stellar Vector's blog as a forum post in #learning (every few minutes, and with
/blog-check). Switched off when LEARNING_FORUM_ID is not set."""

import asyncio
import logging
from datetime import timedelta
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import run_now
from core import checks
from core.scheduler import Job, every_minutes
from feeds import blog
from feeds.blog import BlogCheckResult
from utils.text import plural

log = logging.getLogger("bot")

CHECK_MINUTES = 10
CHECK_TIMEOUT = timedelta(minutes=3)
# Room to wait for a check in progress and then run one
JOB_TIMEOUT = 2 * CHECK_TIMEOUT + timedelta(minutes=1)
ALERT_AFTER = timedelta(hours=24)


class BlogPostsFailed(Exception):
    """The feed had new posts, but none of them could be posted in the forum."""


def check_reply(result: BlogCheckResult) -> str:
    if result.recorded:
        was, them = ("was", "it") if result.recorded == 1 else ("were", "them")
        return (
            f":white_check_mark: First blog check: the {plural(result.recorded, 'current post')} {was} recorded"
            f" without posting {them}. New posts get a forum post from now on."
        )
    text = f"Blog checked: {plural(result.created, 'forum post')} created."
    if not result.failed:
        return f":white_check_mark: {text}"
    return (
        f":warning: {text} {result.failed} could not be created;"
        f" {'it is' if result.failed == 1 else 'they are'} tried again on the next check."
    )


class BlogFeed(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot
        # The scheduled check and /blog-check take turns, so they never post the same blog post twice
        self._lock = asyncio.Lock()

    @property
    def forum_id(self) -> int | None:
        return self.bot.settings.channels.learning_forum

    async def cog_load(self) -> None:
        if self.forum_id is None:
            return
        self.bot.scheduler.register(
            Job(
                "blog-check",
                every_minutes(CHECK_MINUTES),
                self.scheduled_check,
                timeout=JOB_TIMEOUT,
                alert_after=ALERT_AFTER,
            )
        )

    async def scheduled_check(self) -> None:
        result = await self.check_blog()
        if result.failed and not result.created:
            raise BlogPostsFailed(f"None of the {plural(result.failed, 'new blog post')} could be posted")

    async def check_blog(self) -> BlogCheckResult:
        async with self._lock:
            result = await asyncio.wait_for(blog.check(self._create_post), timeout=CHECK_TIMEOUT.total_seconds())
        log.info(f"Blog check done: {result}")
        return result

    async def _create_post(self, title: str, body: str, tag_names: list[str]) -> None:
        assert self.forum_id is not None
        forum = cast(discord.ForumChannel, await self.bot.channel(self.forum_id))
        await forum.create_thread(
            name=title,
            content=body,
            applied_tags=blog.find_tags(forum.available_tags, tag_names),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(
        name="blog-check", description="Share the new posts on Stellar Vector's blog in #learning right away"
    )
    @checks.admins_only()
    async def blog_check_command(self, interaction: discord.Interaction) -> None:
        if self.forum_id is None:
            await interaction.response.send_message(
                content=":warning: LEARNING_FORUM_ID is not configured, so there is no forum to post new blog posts"
                " in.",
                ephemeral=True,
            )
            return

        result = await run_now(interaction, self.check_blog(), JOB_TIMEOUT, "blog check")
        if result is not None:
            await interaction.edit_original_response(content=check_reply(result))
