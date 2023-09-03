# Creates a backup of a ctf category and its contents
# Can be run from a ctf category channel
#   by an administrator or ctf operator
import core.bot as bot
import discord
from discord import app_commands
from utils.archive.ctf import CtfArchive


@bot.client.tree.command(name="archive-ctf", description="Archive a CTF", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
@app_commands.describe(name="The CTF name (exactly)")
async def archive_ctf(interaction: discord.Interaction, name: str):
    await interaction.response.defer(thinking=True)

    category = discord.utils.get(interaction.guild.channels, name="⚡ " + name)

    if not category:
        await interaction.edit_original_response(content=f"That CTF does not exist.")
        return

    channels = category.channels

    archive = await CtfArchive.init(name, channels)
    archive.generate_files()
    archive.save()

    await interaction.edit_original_response(content=f"{interaction.user.mention} archived {name}")
