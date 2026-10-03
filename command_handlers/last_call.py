# Moves the CTF's join message to the bottom of #upcoming-ctfs as a last call, with the same players
# Can be run from the CTF's #bot channel
#   by an administrator, manager or moderator
from datetime import datetime, timezone

import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_join, ctf_places
from utils.ctf_places import Place


@bot.client.tree.command(name="last-call", description="Post the CTF's join message again as a last call",
                         guild=bot.guild)
@app_commands.checks.has_any_role(*bot.STAFF_ROLES)
async def last_call(interaction: discord.Interaction):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    try:
        ctf = await ctf_join.last_call(interaction.guild, location.ctf, bot.channel_id("UPCOMING_CTFS_CHANNEL_ID"),
                                       datetime.now(timezone.utc))
    except ctf_join.LastCallRefused as e:
        await interaction.edit_original_response(content=f":no_entry: {e}")
        return

    await interaction.edit_original_response(
        content=f"Done: last call posted in <#{ctf.join_channel_id}> :rotating_light:")

@last_call.error
async def error_on_last_call_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
