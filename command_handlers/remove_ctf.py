# Deletes a CTF's channels, category and role, and records that the CTF was removed
# Refuses a CTF that was not archived, unless forced
# Can be run from the CTF's #bot channel
#   by an administrator or manager
import logging
from datetime import datetime, timezone

import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_places, ctfs
from utils.ctf_places import Place


@bot.client.tree.command(name="remove-ctf", description="Remove a CTF (PERMANENTLY)", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
@app_commands.describe(force="Also remove it when it was never archived")
async def remove_ctf(interaction: discord.Interaction, force: bool = False):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    ctf = location.ctf
    if ctf.archived_at is None and not force:
        await interaction.response.send_message(content=f":no_entry: I refuse to remove this CTF because it was never archived. Run `/archive-ctf` first.")
        return

    await interaction.response.send_message(content=f"Removing {ctf.name}...")

    guild = interaction.guild
    category = guild.get_channel(ctf.category_id)
    content = [] if category is None else ctf_places.without_bot_channel(ctf, category.channels)
    not_deleted = await _delete([*content, guild.get_role(ctf.role_id)])
    if not_deleted:
        # #bot and the CTF's row stay, so the command can be run here again
        await interaction.edit_original_response(content=f":warning: These could not be deleted: {', '.join(not_deleted)}\nDelete them by hand or run `/remove-ctf` again.")
        return

    # The reply was in #bot, which is deleted now as well, so the admins are told in the admin channel
    not_deleted = await _delete([guild.get_channel(ctf.bot_channel_id), category])
    ctfs.mark_removed(ctf.id, datetime.now(timezone.utc))
    logging.getLogger("bot").info(f"CTF {ctf.name!r} removed by {interaction.user}")

    message = f"{interaction.user.mention} removed the CTF {ctf.name}"
    if not_deleted:
        message += f"\n:warning: These could not be deleted, delete them by hand: {', '.join(not_deleted)}"
    await bot.alert_admins(message)

async def _delete(discord_objects):
    """Delete each of the Discord objects that exists (None is skipped); a failure is logged and the rest is still
    deleted. Returns the names of the ones that could not be deleted."""
    not_deleted = []
    for discord_object in discord_objects:
        if discord_object is None:
            continue
        try:
            await discord_object.delete()
        except Exception:
            logging.getLogger("bot").exception(f"Could not delete {discord_object!r} of a removed CTF")
            not_deleted.append(f"`{discord_object.name}`")
    return not_deleted

@remove_ctf.error
async def remove_ctf_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
