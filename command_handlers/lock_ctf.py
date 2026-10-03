# Makes the CTF read-only for everyone but the staff, locks its threads and archives it
# Can be run from the CTF's #bot channel
#   by an administrator or manager
from datetime import datetime, timezone

import core.bot as bot
import core.config as config_helpers
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_archive, ctf_lock, ctf_places
from utils.ctf_places import Place


def lock_roles():
    return ctf_lock.LockRoles(member=config_helpers.role_name(bot.config, "MEMBER_ROLE"),
                              writers=frozenset(bot.STAFF_ROLES))


@bot.client.tree.command(name="lock-ctf", description="Make the CTF read-only and archive it", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
async def lock_ctf(interaction: discord.Interaction):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    try:
        locked = await ctf_lock.lock(interaction.guild, location.ctf, lock_roles(), datetime.now(timezone.utc),
                                     ctf_archive.archive)
    except ctf_lock.LockRefused as e:
        await interaction.edit_original_response(content=f":no_entry: {e}")
        return

    try:
        await interaction.edit_original_response(content=locked.notice)
    except discord.HTTPException:
        # A long archive outlasts the interaction (15 minutes); the notice still goes to #bot
        await interaction.channel.send(locked.notice)

@lock_ctf.error
async def error_on_lock_ctf_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
