# Shows the available commands
# Can be run in any channel by all members of Stellar Vector
import core.bot as bot
from discord import app_commands
import discord


@bot.client.tree.command(name="help", description="Show the possible commands", guild=bot.guild)
async def create_challenge(interaction: discord.Interaction):
    help_message = f"""Hi there :wave:
These are the commands I understand:
`/add-category` - Create a channel per challenge category: Use in the main channel of a CTF and give the categories, comma-separated (`web, crypto, pwn`).
`/create-challenge` - Create a challenge channel: Use in the main channel of a CTF and provide the name and category of the challenge.
`/solved` - Mark a challenge as solved: Use in any challenge channel and provide the flag as proof.
`/help` - Show this message
To play a CTF, click **Join** on its message in #upcoming-ctfs; the **Leave** button on the guide in its main channel takes you out again.

For admins, managers and moderators, in the #bot channel of a CTF:
`/add-player` - Give a member access to the CTF and put them on its player list.
`/remove-player` - Take a member's access to the CTF away and take them off its player list.
`/last-call` - Post the CTF's join message again at the bottom of #upcoming-ctfs, as a last call.

For admins and managers:
`/setup-ctf` - Set up a new CTF: its role, category, main channel and #bot channel. Give the CTFtime event ID to also store its dates.
In the #bot channel of a CTF:
`/release-ctf` - Open the CTF to all members.
`/archive-ctf` - Archive the CTF's channels.
`/remove-ctf` - Delete the CTF's channels, category and role. Refused when it was never archived, unless `force` is set.

For admins:
`/calendar-sync` - Sync the calendar into the Discord events right away, instead of waiting for the next automatic sync.
`/ctftime-check` - Check the CTFs on the calendar for date changes on CTFtime right away, instead of waiting for the daily check.
`/blog-check` - Share the new posts on Stellar Vector's blog in #learning right away.

In order to do one of the following things, **ask an admin**:
* You want to play a CTF, but can't join it with its **Join** button.
* You would like to play a specific CTF that is not in our planning.
* You mistakenly marked a challenge as solved and would like to revert it.
* You played in a CTF and would like to review the discussion from a Discord challenge channel that is not visible anymore."""

    await interaction.response.send_message(help_message, ephemeral=True)
