# Shows the available commands
# Can be run in any channel by all members of Stellar Vector
import core.bot as bot
import discord


HELP_MESSAGE = """**Everyone**
`/help` - Show this message
`/add-category` - Add challenge categories (CTF main channel)
`/create-challenge` - Start or join a challenge thread (category channel)
`/solved` - Mark a challenge solved (challenge thread)
Join a CTF with **Join** in #upcoming-ctfs, leave it with **Leave** on its guide.

**Staff**
`/add-player`, `/remove-player` - Add or remove a player (CTF #bot)
`/last-call` - Repost the join message as a last call (CTF #bot)
`/unsolve` - Mark a challenge unsolved (challenge thread)
`/ctf-status` - Show the managed CTFs

**Admins and managers**
`/setup-ctf` - Set up a new CTF
`/ctftime-table` - Post upcoming CTFs in #ctf-selection
`/archive-channel` - Archive a non-CTF channel
`/release-ctf`, `/lock-ctf`, `/archive-ctf`, `/remove-ctf` - Release, lock, archive or remove the CTF (CTF #bot)

**Admins**
`/calendar-sync`, `/ctftime-check`, `/blog-check` - Run the calendar sync, CTFtime check or blog check now

Anything else? Ask an admin."""


@bot.client.tree.command(name="help", description="Show the possible commands", guild=bot.guild)
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(HELP_MESSAGE, ephemeral=True)
