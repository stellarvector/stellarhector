# Mirrors the ICS calendar feed (ICS_URL) into the server's Discord scheduled events,
# announcing each new event in CALENDAR_CHANNEL_ID
# Runs by itself every ICS_POLL_MINUTES; switched off entirely when ICS_URL is not set
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


async def run_calendar_sync():
    """Sync the calendar feed into Discord once and return the calendar_sync.Summary.

    Raises calendar_sync.FeedError when the feed can't be downloaded or parsed, so the scheduler logs it.
    """
    guild = bot.client.get_guild(bot.guild.id) or await bot.client.fetch_guild(bot.guild.id)

    channel_id = bot.channel_id("CALENDAR_CHANNEL_ID")
    announce_channel = None if channel_id is None else await bot.channel(channel_id)

    summary = await calendar_sync.sync(guild, ICS_URL, bot.TIMEZONE, LOOKAHEAD, announce_channel, _ping_role(guild))
    logging.getLogger("bot").info(f"Calendar sync done: {summary}")
    return summary


def _ping_role(guild):
    if not PING_ROLE:
        return None

    role = discord.utils.get(guild.roles, name=PING_ROLE)
    if role is None:
        logging.getLogger("bot").warning(f"ICS_PING_ROLE {PING_ROLE!r} is not a role on the server, announcing without a ping")
    return role


if ICS_URL:
    scheduler.register(scheduler.Job("calendar-sync", scheduler.every_minutes(POLL_MINUTES), run_calendar_sync))
