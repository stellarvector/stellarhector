# Sets the name back to the original and sorts the challenges
# Can be run in a solved challenge by an admin or manager.
import core.bot as bot
import discord
from discord import app_commands
from utils.ctf import get_new_channel_position
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_places
from utils.ctf_places import Place


@bot.client.tree.command(description="Use in a challenge to revert the solving of the challenge.", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
async def unsolve(interaction):
    # TODO ctf-lifecycle 07: only in a challenge thread, once challenges are threads; until then challenge channels
    # are what the lookup calls category channels
    location = await ctf_places.locate_or_refuse(interaction, Place.CATEGORY)
    if location is None:
        return

    await interaction.response.defer(thinking=True)
    message_id = interaction.channel.last_message_id

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
