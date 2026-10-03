# Sets up a CTF: its role, category, main channel with the pinned bot guide and #bot channel, its row in ctfs, and its
# join message in #upcoming-ctfs
# Can be run from any channel
#   by an administrator or manager
import core.bot as bot
import core.ctf_settings as ctf_settings
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_setup


@bot.client.tree.command(name="setup-ctf", description="Set up a new CTF", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
@app_commands.rename(ctftime_id="ctftime-id")
@app_commands.describe(name="The CTF name", ctftime_id="The CTF's event ID on CTFtime, for its dates and the automatic timeline")
async def setup_ctf_command(interaction: discord.Interaction, name: str, ctftime_id: int | None = None):
    await interaction.response.defer(thinking=True)

    try:
        ctf = await ctf_setup.setup_ctf(interaction.guild, name, ctftime_id, ctf_settings.setup_settings())
    except ctf_setup.SetupRefused as e:
        await interaction.edit_original_response(content=f":no_entry: {e}")
        return

    await interaction.edit_original_response(content=f"Done: CTF is set up :raised_hands:\nGo to the <#{ctf.main_channel_id}> channel to start adding challenges.")

@setup_ctf_command.error
async def error_on_setup_ctf_command(interaction: discord.Interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
