# Shares every new post on Stellar Vector's blog as a forum post in LEARNING_FORUM_ID
# Switched off entirely when LEARNING_FORUM_ID is not set
# Runs by itself every blog_feed.CHECK_MINUTES minutes
# Alerts ADMIN_CHANNEL_ID once the check has been failing for blog_feed.ALERT_AFTER in a row, and when it works again
# /blog-check runs the check right away; can be run from any channel
#   by an administrator
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import core.bot as bot
import core.scheduler as scheduler
import discord
from discord import app_commands
from error_handlers.default import default as default_error_handler
from error_handlers.permissions import check_role_error
from utils import blog_feed

# Shorter than TIMEOUT, so a check that hangs is counted as a failed check instead of stopped by the scheduler
CHECK_TIMEOUT = timedelta(minutes=3)
# Room to wait for a running check (CHECK_TIMEOUT and its alert) and then run one, for the job and /blog-check alike
TIMEOUT = 2 * (CHECK_TIMEOUT + scheduler.ALERT_TIMEOUT) + timedelta(minutes=1)

_health = blog_feed.CheckHealth()
# The scheduled check and /blog-check take turns, so they never post the same blog post twice
_lock = asyncio.Lock()


async def run_blog_check():
    """The blog-check job: check_blog, but a skipped or timed out check returns None instead of raising, since it has
    been handled already and is no reason for the scheduler to retry or alert."""
    try:
        return await check_blog()
    except (blog_feed.FeedError, asyncio.TimeoutError):
        return None


async def check_blog():
    """Check the blog feed once and return the blog_feed.CheckResult, or None when LEARNING_FORUM_ID is not set.
    Waits for a check that is already running.

    Raises blog_feed.FeedError when the feed can't be downloaded or parsed; nothing changed then, and it is logged.
    Raises asyncio.TimeoutError when the check took longer than CHECK_TIMEOUT; the next check carries on where it left
    off. A failing check is only logged, as the next one is a few minutes later anyway; once the checks have been failing
    for blog_feed.ALERT_AFTER in a row the admins are alerted once, and told when it works again.
    """
    forum_id = bot.channel_id("LEARNING_FORUM_ID")
    if forum_id is None:
        return None

    async with _lock:
        try:
            result = await asyncio.wait_for(blog_feed.check(_forum_poster(forum_id)), timeout=CHECK_TIMEOUT.total_seconds())
        except blog_feed.FeedError as e:
            logging.getLogger("bot").warning(f"Blog check skipped: {e}")
            await _failed(e)
            raise
        except asyncio.TimeoutError:
            logging.getLogger("bot").error(f"Blog check timed out after {CHECK_TIMEOUT}")
            await _failed(f"The check took longer than {CHECK_TIMEOUT.total_seconds() / 60:g} minutes")
            raise

        logging.getLogger("bot").info(f"Blog check done: {result}")
        reason = blog_feed.failure_reason(result)
        if reason is not None:
            logging.getLogger("bot").warning(f"Blog check failed: {reason}")
            await _failed(reason)
        elif _health.succeeded() and await _alert(":white_check_mark: The blog check works again."):
            _health.recovery_posted()
        return result


async def _failed(error):
    """Count a failed check, and alert the admins when it has been failing long enough."""
    if _health.failed(datetime.now(timezone.utc)) and await _alert(blog_feed.alert_message(_health.failing_since, error)):
        _health.alert_posted()


async def _alert(message):
    """Post message for the admins. Returns whether it was posted; a failure is logged."""
    try:
        await asyncio.wait_for(bot.alert_admins(message), timeout=scheduler.ALERT_TIMEOUT.total_seconds())
    except Exception:
        logging.getLogger("bot").exception(f"Could not post the blog check alert: {message}")
        return False
    return True


def _forum_poster(forum_id):
    """The create_post for blog_feed.check: creates the forum post in the forum with forum_id."""
    async def create_post(title, body, tag_names):
        forum = await bot.channel(forum_id)
        await forum.create_thread(name=title, content=body, applied_tags=blog_feed.find_tags(forum.available_tags, tag_names),
                                  allowed_mentions=discord.AllowedMentions.none())
    return create_post


if bot.channel_id("LEARNING_FORUM_ID") is not None:
    # A failing check is alerted through _health; alert_after covers the failures that reach the scheduler
    scheduler.register(scheduler.Job("blog-check", scheduler.every_minutes(blog_feed.CHECK_MINUTES), run_blog_check,
                                     timeout=TIMEOUT, alert_after=blog_feed.ALERT_AFTER))


@bot.client.tree.command(name="blog-check", description="Share the new posts on Stellar Vector's blog in #learning right away", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.ADMIN_ROLES)
async def blog_check_command(interaction: discord.Interaction):
    if bot.channel_id("LEARNING_FORUM_ID") is None:
        await interaction.response.send_message(content=":warning: LEARNING_FORUM_ID is not configured, so there is no forum to post new blog posts in.", ephemeral=True)
        return

    # Downloading the feed, creating the forum posts, and waiting for a scheduled check that is running, can take longer than Discord waits for a reply
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        # Like the job, so a hanging check can't hold the lock and keep the scheduled checks waiting
        result = await asyncio.wait_for(check_blog(), timeout=TIMEOUT.total_seconds())
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
