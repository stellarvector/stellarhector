# Sets up a CTF: its role, category, main channel with the pinned bot guide and #bot channel, its row in ctfs, and its
# join message in #upcoming-ctfs
# Can be run from any channel
#   by an administrator or manager
import core.bot as bot
import core.config as config_helpers
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_setup


def settings():
    def role(key):
        return config_helpers.role_name(bot.config, key)

    return ctf_setup.Settings(admin_role=role("ADMIN_ROLE"), manager_role=role("MANAGER_ROLE"),
                              moderator_role=role("MODERATOR_ROLE"), member_role=role("MEMBER_ROLE"),
                              role_color=int(bot.config.get("CTF_ROLE_COLOR_HEX"), 16),
                              upcoming_channel_id=bot.channel_id("UPCOMING_CTFS_CHANNEL_ID"))


@bot.client.tree.command(name="setup-ctf", description="Set up a new CTF", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
@app_commands.rename(ctftime_id="ctftime-id")
@app_commands.describe(name="The CTF name", ctftime_id="The CTF's event ID on CTFtime, for its dates and the automatic timeline")
async def setup_ctf_command(interaction: discord.Interaction, name: str, ctftime_id: int | None = None):
    await interaction.response.defer(thinking=True)

    try:
        ctf = await ctf_setup.setup_ctf(interaction.guild, name, ctftime_id, settings())
    except ctf_setup.SetupRefused as e:
        await interaction.edit_original_response(content=f":no_entry: {e}")
        return

    await interaction.edit_original_response(content=f"Done: CTF is set up :raised_hands:\nGo to the <#{ctf.main_channel_id}> channel to start adding challenges.")

@setup_ctf_command.error
async def error_on_setup_ctf_command(interaction: discord.Interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
