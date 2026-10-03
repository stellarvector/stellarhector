# Removes a member from a CTF: takes away its role and takes them off its player list and join message
# Can be run from the CTF's #bot channel
#   by an administrator, manager or moderator
import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_join, ctf_places, ctfs
from utils.ctf_places import Place


@bot.client.tree.command(name="remove-player", description="Remove a player from a ctf", guild=bot.guild)
@app_commands.describe(player="Player")
@app_commands.checks.has_any_role(*bot.STAFF_ROLES)
async def remove_player(interaction, player: discord.Member):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True, ephemeral=True)

    ctf = location.ctf
    ctf_role = interaction.guild.get_role(ctf.role_id)
    if ctf_role is not None:
        await player.remove_roles(ctf_role)
    ctfs.remove_player(ctf.id, player.id)
    await ctf_join.refresh_join_message(interaction.guild, ctf)
    await interaction.edit_original_response(content=f"{player.mention} was removed as player from `{ctf.name}`")

@remove_player.error
async def remove_player_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
