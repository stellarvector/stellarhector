# Creates a backup of a CTF's channels and their contents, and records that the CTF was archived
# Can be run from the CTF's #bot channel
#   by an administrator or manager
from datetime import datetime, timezone

import core.bot as bot
import discord
from discord import app_commands
from utils import ctf_archive, ctf_places
from utils.ctf_places import Place
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(name="archive-ctf", description="Archive a CTF", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
async def archive_ctf(interaction: discord.Interaction):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    ctf = location.ctf
    await ctf_archive.archive(interaction.guild, ctf, datetime.now(timezone.utc))

    await interaction.edit_original_response(content=f"{interaction.user.mention} archived {ctf.name}")

@archive_ctf.error
async def archive_ctf_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
