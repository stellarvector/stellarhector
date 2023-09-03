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

In order to do one of the following things, **ask an admin**:
* You really want to join in playing this CTF, but have not been added yet.
* You would like to play a specific CTF that is not in our planning.
* You mistakenly marked a challenge as solved and would like to revert it.
* You played in a CTF and would like to review the discussion from a Discord challenge channel."""

    await interaction.response.send_message(help_message, ephemeral=True)
