# Shows the CTFs the bot manages: their stage, next automatic step and players, only to who runs it
# Can be run from any channel
#   by an administrator, manager or moderator
from datetime import datetime, timezone

import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_status, ctfs


@bot.client.tree.command(name="ctf-status", description="Show the CTFs the bot manages and what happens next", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.STAFF_ROLES)
async def ctf_status_command(interaction: discord.Interaction):
    entries = [(ctf, ctfs.players(ctf.id)) for ctf in ctfs.managed()]
    first, *rest = ctf_status.report(entries, interaction.guild_id, datetime.now(timezone.utc))

    await interaction.response.send_message(first, ephemeral=True)
    for message in rest:
        await interaction.followup.send(message, ephemeral=True)

@ctf_status_command.error
async def error_on_ctf_status_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
