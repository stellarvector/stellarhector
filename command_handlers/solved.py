# Sets the name to solved_{name} and moves the challenge down
# Can be run in a challenge channel by all players of this ctf
import core.bot as bot
from discord import app_commands
import discord
from utils.ctf import get_new_channel_position
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_places
from utils.ctf_places import Place


@bot.client.tree.command(description="Use in a challenge to indicate you have solved the challenge.", guild=bot.guild)
@app_commands.describe(flag="The correct flag for this challenge")
async def solved(interaction, flag: str):
    # TODO ctf-lifecycle 08: only in a challenge thread, renaming the thread; until then challenge channels
    # are what the lookup calls category channels
    location = await ctf_places.locate_or_refuse(interaction, Place.CATEGORY)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    if interaction.user.get_role(location.ctf.role_id) is None:
        await interaction.edit_original_response(content="You are not playing this CTF so you can't mark a challenge solved.\nIf you are playing please ask an admin.")
        return

    if "solved" in interaction.channel.name:
        await interaction.edit_original_response(content="This challenge is already solved.\nIf this was a mistake please contact an admin.")
        return

    new_name = f"solved_{interaction.channel.name}"
    new_position = get_new_channel_position(interaction.channel.category, new_name)

    await interaction.channel.edit(name=new_name,position=new_position)
    await interaction.edit_original_response(content=f"Nice, great work! :partying_face:\nSolved by {interaction.user.mention} with `{flag}`.")

@solved.error
async def error_on_create_challenge_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
