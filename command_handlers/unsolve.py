# Marks a solved challenge unsolved again: its thread is renamed back to `<slug>` and the overview is updated
# Can be run in a challenge thread by administrators, managers and moderators
import core.bot as bot
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_challenges, ctf_places


@bot.client.tree.command(description="Use in a challenge to revert the solving of the challenge.", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.STAFF_ROLES)
async def unsolve(interaction):
    location = ctf_places.locate(interaction.channel)
    challenge = ctf_challenges.challenge_at(location, interaction.channel)
    if challenge is None:
        await interaction.response.send_message(f":no_entry: {ctf_challenges.NOT_IN_CHALLENGE}", ephemeral=True)
        return

    if location.ctf.locked_at is not None:
        await interaction.response.send_message(f":no_entry: {ctf_places.LOCKED}", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    if not await ctf_challenges.mark_solved(interaction.guild, location.ctf, interaction.channel, challenge, False):
        await interaction.edit_original_response(content="This challenge is not solved.\nIn order to mark a challenge as unsolved it should have been marked as solved.")
        return

    await interaction.edit_original_response(content=f"Turns out this wasn't a solve after all :pensive:")

@unsolve.error
async def error_on_unsolve_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
