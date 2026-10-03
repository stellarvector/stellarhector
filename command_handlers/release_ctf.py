# Releases the CTF channels to all members
# Can be run from the CTF's #bot channel
#   by an administrator or manager
import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler
from utils import ctf_places
from utils.ctf_places import Place


@bot.client.tree.command(name="release-ctf", description="Release the CTF to all members", guild=bot.guild)
@app_commands.checks.has_any_role(*bot.MANAGER_ROLES)
async def release_ctf(interaction: discord.Interaction):
    location = await ctf_places.locate_or_refuse(interaction, Place.BOT)
    if location is None:
        return

    await interaction.response.defer(thinking=True)

    ctf = location.ctf
    ctf_category = interaction.guild.get_channel(ctf.category_id)

    member_role: discord.Role = discord.utils.get(interaction.guild.roles, name=bot.config.get("MEMBER_ROLE"))
    ctf_role: discord.Role = interaction.guild.get_role(ctf.role_id)
    admin_role: discord.Role = discord.utils.get(interaction.guild.roles, name=bot.config.get("ADMIN_ROLE"))

    if ctf_role is None:
        await interaction.edit_original_response(content=f":no_entry: The role of `{ctf.name}` no longer exists.")
        return

    await ctf_category.edit(overwrites={
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False,view_channel=False,manage_channels=False),
        member_role: discord.PermissionOverwrite(read_messages=True,view_channel=True),
        ctf_role: discord.PermissionOverwrite(read_messages=True,view_channel=True),
        admin_role: discord.PermissionOverwrite(read_messages=True,view_channel=True,manage_channels=True)
    })

    # #bot stays for staff only
    channels = ctf_places.without_bot_channel(ctf, ctf_category.channels)
    for channel in channels:
        await channel.edit(sync_permissions=True)

    await interaction.edit_original_response(content=f"Done; CTF released, welcome everyone! :wave:")

@release_ctf.error
async def error_on_release_ctf_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
