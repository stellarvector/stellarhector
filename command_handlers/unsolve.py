# Sets the name back to the original and sorts the challenges
# Can be run in a solved challenge by an admin or ctf-operator.
import core.bot as bot
import discord
from discord import app_commands
from utils.ctf import get_new_channel_position
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(description="Use in a challenge to revert the solving of the challenge.", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
async def unsolve(interaction):
    await interaction.response.defer(thinking=True)
    message_id = interaction.channel.last_message_id

    ctf_category = interaction.channel.category
    ctf_role = discord.utils.get(interaction.guild.roles, name=ctf_category.name)

    if not ctf_role:
        await interaction.edit_original_response(content="This is not a ctf challenge channel, this command can only be run from a challenge channel.")
        return

    if "solved" not in interaction.channel.name:
        await interaction.edit_original_response(content="This challenge is not solved.\nIn order to mark a challenge as unsolved it should have been marked as solved.")
        return

    new_name = interaction.channel.name.replace("solved_", "")
    new_position = get_new_channel_position(interaction.channel.category, new_name)

    await interaction.channel.edit(name=new_name, position=new_position)
    await interaction.edit_original_response(content=f"Turns out this wasn't a solve after all :pensive:")

@unsolve.error
async def error_on_create_challenge_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
