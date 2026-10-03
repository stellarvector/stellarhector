# Marks a challenge solved: its thread is renamed to `✅ <slug>` and stays open, and the overview is updated
# Can be run in a challenge thread by all players of this ctf (i.e. having the ctf role)
import core.bot as bot
from discord import app_commands
from error_handlers.default import default as default_error_handler
from utils import ctf_challenges, ctf_places


@bot.client.tree.command(description="Use in a challenge to indicate you have solved the challenge.", guild=bot.guild)
@app_commands.describe(flag="The correct flag for this challenge")
async def solved(interaction, flag: str):
    location = ctf_places.locate(interaction.channel)
    challenge = ctf_challenges.challenge_at(location, interaction.channel)
    if challenge is None:
        await interaction.response.send_message(f":no_entry: {ctf_challenges.NOT_IN_CHALLENGE}", ephemeral=True)
        return

    if interaction.user.get_role(location.ctf.role_id) is None:
        await interaction.response.send_message(
            ":no_entry: You are not playing this CTF so you can't mark a challenge solved.\n"
            "If you are playing please ask a moderator.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    if not await ctf_challenges.mark_solved(interaction.guild, location.ctf, interaction.channel, challenge, True):
        await interaction.edit_original_response(content="This challenge is already solved.\nIf this was a mistake please ask a moderator.")
        return

    await interaction.edit_original_response(content=f"Nice, great work! :partying_face:\nSolved by {interaction.user.mention} with `{flag}`.")

@solved.error
async def error_on_solved_command(interaction, error):
    await default_error_handler(interaction, error)
