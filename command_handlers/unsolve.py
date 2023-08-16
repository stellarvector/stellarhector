# Sets the name back to the original and sorts the challenges
# Can be run in a solved challenge by an admin or ctf-operator.
import core.bot as bot
import discord
from discord import app_commands
from utils.ctf import get_new_channel_position


@bot.client.tree.command(description="Use in a challenge to revert the solving of the challenge.", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
async def unsolve(interaction):
    await interaction.response.defer()
    message_id = interaction.channel.last_message_id

    ctf_category = interaction.channel.category
    ctf_role = discord.utils.get(interaction.guild.roles, name=ctf_category.name)

    if not ctf_role:
        # TODO: Can still be run from the main channel for each ctf
        await interaction.followup.edit_message(message_id, content="This is not a ctf challenge channel, this command can only be run from a challenge channel.", ephemeral=True)
        return

    if "solved" not in interaction.channel.name:
        await interaction.followup.edit_message(message_id, content="This challenge is not solved.\nIn order to mark a challenge as unsolved it should have been marked as solved.", ephemeral=True)
        return

    new_name = interaction.channel.name.replace("solved_", "")
    new_position = get_new_channel_position(interaction.channel.category, new_name)

    await interaction.channel.edit(name=new_name, position=new_position)
    await interaction.response.send_message(f"Awww, it turned out this wasn't a solve after all :pensive:")
