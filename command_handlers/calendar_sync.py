# Mirrors the ICS calendar feed (ICS_URL) into the server's Discord scheduled events,
# announcing each new event in CALENDAR_CHANNEL_ID
# Runs by itself every ICS_POLL_MINUTES; switched off entirely when ICS_URL is not set
# Alerts ADMIN_CHANNEL_ID once the feed has been broken for calendar_sync.FAILURES_BEFORE_ALERT syncs in a row
import asyncio
import logging
from datetime import timedelta

import core.bot as bot
import core.config as config_helpers
import core.scheduler as scheduler
import discord
from utils import calendar_sync

ICS_URL = (bot.config.get("ICS_URL") or "").strip()
POLL_MINUTES = config_helpers.positive_int(bot.config, "ICS_POLL_MINUTES", 15)
LOOKAHEAD = timedelta(days=config_helpers.positive_int(bot.config, "ICS_LOOKAHEAD_DAYS", 30))
PING_ROLE = (bot.config.get("ICS_PING_ROLE") or "").strip()

_health = calendar_sync.FeedHealth()


async def run_calendar_sync():
    """Sync the calendar feed into Discord once and return the calendar_sync.Summary, or None when the sync was
    skipped because the feed can't be downloaded or parsed, or is suspiciously empty.

    A skipped sync changes nothing and is only logged, so the next one waits for the poll interval like any other;
    after calendar_sync.FAILURES_BEFORE_ALERT skipped syncs in a row the admins are alerted once, and told when it works again.
    """
    guild = bot.client.get_guild(bot.guild.id) or await bot.client.fetch_guild(bot.guild.id)

    channel_id = bot.channel_id("CALENDAR_CHANNEL_ID")
    announce_channel = None if channel_id is None else await bot.channel(channel_id)

    try:
        summary = await calendar_sync.sync(guild, ICS_URL, bot.TIMEZONE, LOOKAHEAD, announce_channel, _ping_role(guild))
    except calendar_sync.FeedError as e:
        logging.getLogger("bot").warning(f"Calendar sync skipped ({_health.failures + 1} in a row): {e}")
        if _health.failed() and await _alert(_alert_message(e)):
            _health.alert_posted()
        return None

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
