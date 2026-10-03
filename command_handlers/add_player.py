# Adds a member to a CTF: gives them its role and puts them on its player list and join message
# Can be run from the CTF's #bot channel
#   by an administrator, manager or moderator
from datetime import datetime, timezone

import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_join, ctf_places, ctfs
from utils.ctf_places import Place


@bot.client.tree.command(name="add-player", description="Add a new player to the ctf", guild=bot.guild)
@app_commands.describe(player="Player")
@app_commands.checks.has_any_role(*bot.STAFF_ROLES)
async def add_player(interaction, player: discord.Member):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    ctf = location.ctf
    ctf_role = interaction.guild.get_role(ctf.role_id)
    if ctf_role is None:
        await interaction.edit_original_response(content=f":no_entry: The role of `{ctf.name}` no longer exists.")
        return

    await player.add_roles(ctf_role)
    ctfs.add_player(ctf.id, player.id, datetime.now(timezone.utc))
    await ctf_join.refresh_join_message(interaction.guild, ctf)
    await interaction.edit_original_response(content=f"{player.mention} was added as player in `{ctf.name}`")

@add_player.error
async def add_player_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
