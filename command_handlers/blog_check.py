# Shares every new post on Stellar Vector's blog as a forum post in LEARNING_FORUM_ID
# Switched off entirely when LEARNING_FORUM_ID is not set
# /blog-check runs the check right away; can be run from any channel
#   by an administrator
import asyncio
import logging

import core.bot as bot
import core.scheduler as scheduler
import discord
from discord import app_commands
from error_handlers.default import default as default_error_handler
from error_handlers.permissions import check_role_error
from utils import blog_feed


async def check_blog():
    """Check the blog feed once and return the blog_feed.CheckResult, or None when LEARNING_FORUM_ID is not set.

    Raises blog_feed.FeedError when the feed can't be downloaded or parsed; nothing changed then, and it is logged.
    """
    forum_id = bot.channel_id("LEARNING_FORUM_ID")
    if forum_id is None:
        return None

    try:
        result = await blog_feed.check(_forum_poster(forum_id))
    except blog_feed.FeedError as e:
        logging.getLogger("bot").warning(f"Blog check skipped: {e}")
        raise
    logging.getLogger("bot").info(f"Blog check done: {result}")
    return result


def _forum_poster(forum_id):
    """The create_post for blog_feed.check: creates the forum post in the forum with forum_id."""
    async def create_post(title, body, tag_names):
        forum = await bot.channel(forum_id)
        await forum.create_thread(name=title, content=body, applied_tags=blog_feed.find_tags(forum.available_tags, tag_names),
                                  allowed_mentions=discord.AllowedMentions.none())
    return create_post


@bot.client.tree.command(name="blog-check", description="Share the new posts on Stellar Vector's blog in #learning right away", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.ADMIN_ROLES)
async def blog_check_command(interaction: discord.Interaction):
    if bot.channel_id("LEARNING_FORUM_ID") is None:
        await interaction.response.send_message(content=":warning: LEARNING_FORUM_ID is not configured, so there is no forum to post new blog posts in.", ephemeral=True)
        return

    # Downloading the feed and creating the forum posts can take longer than Discord waits for a reply
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        result = await asyncio.wait_for(check_blog(), timeout=scheduler.DEFAULT_TIMEOUT.total_seconds())
    except blog_feed.FeedError as e:
        await interaction.edit_original_response(content=blog_feed.skipped_reply(e))
        return
    except asyncio.TimeoutError:
        logging.getLogger("bot").error("/blog-check timed out")
        await interaction.edit_original_response(content=":warning: The blog check took too long and was stopped. The next check carries on where it left off.")
        return

    await interaction.edit_original_response(content=blog_feed.reply(result))

@blog_check_command.error
async def error_on_blog_check_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
