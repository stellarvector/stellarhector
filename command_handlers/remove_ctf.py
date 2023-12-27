import core.bot as bot
import discord
import datetime
import os
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler

@bot.client.tree.command(name="remove-ctf", description="Remove a CTF (PERMANENTLY)", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
@app_commands.describe(name="The CTF name (exactly)")
async def remove_ctf(interaction: discord.Interaction, name: str):
    await interaction.response.defer(thinking=True)

    archive_path = bot.config.get("ARCHIVE_LOCAL_PATH")
    year = datetime.datetime.now().year
    force = False

    if name.startswith("!!!"):
        name = name[3:]
        force = True

    if not force and not os.path.exists(f"{archive_path}{year}/{name}/"):
        await interaction.edit_original_response(content=f":no_entry: I refuse to remove this CTF because I cannot find an archive of it (in the current year).")
        return

    category = discord.utils.get(interaction.guild.channels, name="⚡ " + name)

    if not category:
        await interaction.edit_original_response(content=f"That CTF does not exist.")
        return

    channels = category.channels
    role = discord.utils.get(interaction.guild.roles, name=category.name)

    for channel in channels:
        await channel.delete()
    await category.delete()

    if role:
        await role.delete()

    await interaction.edit_original_response(content=f"{interaction.user.mention} removed {name}")

@remove_ctf.error
async def remove_ctf_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
