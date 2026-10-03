# Checks the CTFs that calendar sessions link to on CTFtime, and alerts ADMIN_CHANNEL_ID when their dates changed
# or they are gone from CTFtime
# Runs by itself every day at 12:00 TIMEZONE
# /ctftime-check runs it right away; can be run from any channel
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
from utils import ctftime_check

# Every CTF is one CTFtime request of at most 30 seconds, so give a handful of slow ones room
TIMEOUT = timedelta(minutes=10)

# The daily check and /ctftime-check take turns, so they never post the same alert twice
_lock = asyncio.Lock()


async def check_ctftime():
    """Check the linked CTFs on CTFtime once and return the ctftime_check.CheckResult. Waits for a check that is
    already running."""
    async with _lock:
        result = await ctftime_check.check(datetime.now(timezone.utc), _alert)
    logging.getLogger("bot").info(f"CTFtime check done: {result}")
    return result


async def _alert(ctftime_id, message):
    """Post message about the CTF with ctftime_id for the admins."""
    # TODO ctf-lifecycle: post in the CTF's #bot channel once the CTF is set up
    await asyncio.wait_for(bot.alert_admins(message), timeout=scheduler.ALERT_TIMEOUT.total_seconds())


scheduler.register(scheduler.Job("ctftime-check", scheduler.daily_at("12:00", bot.TIMEZONE), check_ctftime, timeout=TIMEOUT))


@bot.client.tree.command(name="ctftime-check", description="Check the CTFs on the calendar for date changes on CTFtime right away", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.ADMIN_ROLES)
async def ctftime_check_command(interaction: discord.Interaction):
    # Asking CTFtime, and waiting for a daily check that is running, can take longer than Discord waits for a reply
    await interaction.response.defer(thinking=True, ephemeral=True)

    try:
        result = await asyncio.wait_for(check_ctftime(), timeout=TIMEOUT.total_seconds())
    except asyncio.TimeoutError:
        logging.getLogger("bot").error("/ctftime-check timed out")
        await interaction.edit_original_response(content=":warning: The CTFtime check took too long and was stopped. The next check carries on where it left off.")
        return

    await interaction.edit_original_response(content=ctftime_check.reply(result))

@ctftime_check_command.error
async def error_on_ctftime_check_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
