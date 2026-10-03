# Releases the CTF channels to all members and closes joining it
# Can be run from the CTF's #bot channel
#   by an administrator or manager
from datetime import datetime, timezone

import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_places, ctf_release
from utils.ctf_places import Place


@bot.client.tree.command(name="release-ctf", description="Release the CTF to all members", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
async def release_ctf(interaction: discord.Interaction):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    try:
        await ctf_release.release(interaction.guild, location.ctf, bot.MEMBER_ROLE, datetime.now(timezone.utc))
    except ctf_release.ReleaseRefused as e:
        await interaction.edit_original_response(content=f":no_entry: {e}")
        return

    await interaction.edit_original_response(content=f"Done; CTF released, welcome everyone! :wave:")

@release_ctf.error
async def error_on_release_ctf_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
