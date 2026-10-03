# Mirrors the ICS calendar feed (ICS_URL) into the server's Discord scheduled events,
# announcing each new event in CALENDAR_CHANNEL_ID
# Runs by itself every ICS_POLL_MINUTES; switched off entirely when ICS_URL is not set
# Alerts ADMIN_CHANNEL_ID once the feed has been broken for calendar_sync.FAILURES_BEFORE_ALERT syncs in a row
# /calendar-sync runs it right away; can be run from any channel
#   by an administrator
import asyncio
import logging
from datetime import timedelta

import core.bot as bot
import core.config as config_helpers
import core.scheduler as scheduler
import discord
from discord import app_commands
from error_handlers.default import default as default_error_handler
from error_handlers.permissions import check_role_error
from utils import calendar_sync

ICS_URL = (bot.config.get("ICS_URL") or "").strip()
POLL_MINUTES = config_helpers.positive_int(bot.config, "ICS_POLL_MINUTES", 15)
LOOKAHEAD = timedelta(days=config_helpers.positive_int(bot.config, "ICS_LOOKAHEAD_DAYS", 30))
PING_ROLE = (bot.config.get("ICS_PING_ROLE") or "").strip()

_health = calendar_sync.FeedHealth()
# The scheduled sync and /calendar-sync take turns, so they never create the same event twice
_lock = asyncio.Lock()


async def run_calendar_sync():
    """The calendar-sync job: sync_calendar, but a skipped sync returns None instead of raising, since it has been
    handled already and is no reason for the scheduler to retry or alert."""
    try:
        return await sync_calendar()
    except calendar_sync.FeedError:
        return None


async def sync_calendar():
    """Sync the calendar feed into Discord once and return the calendar_sync.Summary. Waits for a sync that is
    already running.

    Raises calendar_sync.FeedError when the sync was skipped because the feed can't be downloaded or parsed, or is
    suspiciously empty. A skipped sync changes nothing and is logged, so the next one waits for the poll interval
    like any other; after calendar_sync.FAILURES_BEFORE_ALERT skipped syncs in a row the admins are alerted once,
    and told when it works again.
    """
    async with _lock:
        guild = bot.client.get_guild(bot.guild.id) or await bot.client.fetch_guild(bot.guild.id)

        channel_id = bot.channel_id("CALENDAR_CHANNEL_ID")
        announce_channel = None if channel_id is None else await bot.channel(channel_id)

        try:
            summary = await calendar_sync.sync(guild, ICS_URL, bot.TIMEZONE, LOOKAHEAD, announce_channel, _ping_role(guild))
        except calendar_sync.FeedError as e:
            logging.getLogger("bot").warning(f"Calendar sync skipped ({_health.failures + 1} in a row): {e}")
            if _health.failed() and await _alert(_alert_message(e)):
                _health.alert_posted()
            raise

        logging.getLogger("bot").info(f"Calendar sync done: {summary}")
        if _health.succeeded():
            await _alert(":white_check_mark: Calendar sync recovered.")
        return summary


def _alert_message(error):
    # Error texts can hold backticks, which would break the inline code
    error_text = str(error).replace("`", "'")[:scheduler.ALERT_ERROR_LENGTH]
    return (f":warning: The calendar sync has been skipped {_health.failures} times in a row, so Discord events no longer"
            f" follow the calendar. It keeps trying every {POLL_MINUTES} minutes. Last error: `{error_text}`")


async def _alert(message):
    """Post message for the admins. Returns whether it was posted; a failure is logged."""
    try:
        await asyncio.wait_for(bot.alert_admins(message), timeout=scheduler.ALERT_TIMEOUT.total_seconds())
    except Exception:
        logging.getLogger("bot").exception(f"Could not post the calendar sync alert: {message}")
        return False
    return True


def _ping_role(guild):
    if not PING_ROLE:
        return None

    role = discord.utils.get(guild.roles, name=PING_ROLE)
    if role is None:
        logging.getLogger("bot").warning(f"ICS_PING_ROLE {PING_ROLE!r} is not a role on the server, announcing without a ping")
    return role


if ICS_URL:
    scheduler.register(scheduler.Job("calendar-sync", scheduler.every_minutes(POLL_MINUTES), run_calendar_sync))


@bot.client.tree.command(name="calendar-sync", description="Sync the calendar into the Discord events right away", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.ADMIN_ROLES)
async def calendar_sync_command(interaction: discord.Interaction):
    if not ICS_URL:
        await interaction.response.send_message(content=":warning: ICS_URL is not configured, so there is no calendar to sync.", ephemeral=True)
        return

    # Downloading the feed, and waiting for a scheduled sync that is running, can take longer than Discord waits for a reply
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        # Like the job, so a hanging sync can't hold the lock and keep the scheduled syncs waiting
        summary = await asyncio.wait_for(sync_calendar(), timeout=scheduler.DEFAULT_TIMEOUT.total_seconds())
    except calendar_sync.FeedError as e:
        await interaction.edit_original_response(content=calendar_sync.skipped_reply(e))
        return
    except asyncio.TimeoutError:
        logging.getLogger("bot").error("/calendar-sync timed out")
        await interaction.edit_original_response(content=":warning: The calendar sync took too long and was stopped. The next sync carries on where it left off.")
        return

    await interaction.edit_original_response(content=calendar_sync.summary_reply(summary))

@calendar_sync_command.error
async def error_on_calendar_sync_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
