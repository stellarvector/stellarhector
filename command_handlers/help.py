# Shows the available commands
# Can be run in any channel by all members of Stellar Vector
import core.bot as bot
from discord import app_commands
import discord


@bot.client.tree.command(name="help", description="Show the possible commands", guild=bot.guild)
async def create_challenge(interaction: discord.Interaction):
    help_message = f"""Hi there :wave:
These are the commands I understand:
`/create-challenge` - Create a challenge channel: Use in the main channel of a CTF and provide the name and category of the challenge.
`/solved` - Mark a challenge as solved: Use in any challenge channel and provide the flag as proof.
`/help` - Show this message

For admins:
`/calendar-sync` - Sync the calendar into the Discord events right away, instead of waiting for the next automatic sync.
`/ctftime-check` - Check the CTFs on the calendar for date changes on CTFtime right away, instead of waiting for the daily check.
`/blog-check` - Share the new posts on Stellar Vector's blog in #learning right away.

In order to do one of the following things, **ask an admin**:
* You really want to join in playing this CTF, but have not been added yet.
* You would like to play a specific CTF that is not in our planning.
* You mistakenly marked a challenge as solved and would like to revert it.
* You played in a CTF and would like to review the discussion from a Discord challenge channel that is not visible anymore."""

    await interaction.response.send_message(help_message, ephemeral=True)
