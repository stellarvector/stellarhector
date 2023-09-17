# Sets the name to solved_{name} and moves the challenge down
# Can be run in a challenge channel by all players of this ctf
import core.bot as bot
from discord import app_commands
import discord
from utils.ctf import get_new_channel_position
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(description="Use in a challenge to indicate you have solved the challenge.", guild=bot.guild)
@app_commands.describe(flag="The correct flag for this challenge")
async def solved(interaction, flag: str):
    await interaction.response.defer(thinking=True)

    ctf_category = interaction.channel.category
    ctf_role = discord.utils.get(interaction.guild.roles, name=ctf_category.name)

    if not ctf_role:
        await interaction.edit_original_response(content="This is not a ctf challenge channel, this command can only be run from a challenge channel.")
        return

    if interaction.user.get_role(ctf_role.id) is None:
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
