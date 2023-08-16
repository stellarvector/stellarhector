# Sets the name to solved_{name} and moves the challenge down
# Can be run in a challenge channel by all players of this ctf
import core.bot as bot
from discord import app_commands
import discord
from utils.ctf import get_new_channel_position


@bot.client.tree.command(description="Use in a challenge to indicate you have solved the challenge.", guild=bot.guild)
@app_commands.describe(flag="The correct flag for this challenge")
async def solved(interaction, flag: str):
    await interaction.response.defer()
    message_id = interaction.channel.last_message_id

    ctf_category = interaction.channel.category
    ctf_role = discord.utils.get(interaction.guild.roles, name=ctf_category.name)

    if not ctf_role:
        # TODO: Can still be run from the main channel for each ctf
        await interaction.followup.edit_message(message_id, content="This is not a ctf challenge channel, this command can only be run from a challenge channel.", ephemeral=True)
        return

    if interaction.user.get_role(ctf_role.id) is None:
        await interaction.followup.edit_message(message_id, content="You are not playing this CTF so you can't add a challenge.\nIf you are playing please ask an admin.", ephemeral=True)
        return

    if "solved" in interaction.channel.name:
        await interaction.followup.edit_message(message_id, content="This challenge is already solved.\nIf this was a mistake please contact an admin.", ephemeral=True)
        return

    new_name = f"solved_{interaction.channel.name}"
    new_position = get_new_channel_position(interaction.channel.category, new_name)

    await interaction.channel.edit(name=new_name,position=new_position)
    await interaction.followup.edit_message(message_id, content=f"Nice, great work! :partying_face:\nSolved by {interaction.user.mention} with `{flag}`.")
