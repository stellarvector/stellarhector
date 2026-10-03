# Posts the upcoming CTFs from CTFtime in #ctf-selection
# Can be run from any channel
#   by an administrator or manager
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctftime_table
from utils.ctftime import CtftimeError

DEFAULT_MONTHS = 2


@bot.client.tree.command(name="ctftime-table", description="Post the upcoming CTFs from CTFtime in #ctf-selection", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
@app_commands.rename(start_month="start-month")
@app_commands.describe(
    start_month="First month, as a month number (11) or YYYY-MM (2026-11); next month when left out",
    months=f"How many months to list; {DEFAULT_MONTHS} when left out")
async def ctftime_table_command(interaction: discord.Interaction, start_month: str = None,
                                months: app_commands.Range[int, 1, 12] = DEFAULT_MONTHS):
    channel_id = bot.channel_id("CTF_SELECTION_CHANNEL_ID")
    if channel_id is None:
        await interaction.response.send_message(content=":warning: CTF_SELECTION_CHANNEL_ID is not configured, so there is nowhere to post the table.", ephemeral=True)
        return

    try:
        start = ctftime_table.parse_start_month(start_month, datetime.now(ZoneInfo(bot.TIMEZONE)).date())
    except ValueError as e:
        await interaction.response.send_message(content=f":warning: {e}", ephemeral=True)
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    channel = bot.client.get_channel(channel_id) or await bot.client.fetch_channel(channel_id)
    try:
        count = await ctftime_table.post_table(channel, start, months, bot.TIMEZONE)
    except CtftimeError as e:
        logging.getLogger("bot").warning(f"/ctftime-table could not reach CTFtime: {e}")
        await interaction.edit_original_response(content=":warning: CTFtime could not be reached, nothing was posted. Try again later.")
        return

    await interaction.edit_original_response(content=f"Done: {count} CTFs posted in {channel.mention}")

@ctftime_table_command.error
async def error_on_ctftime_table_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
