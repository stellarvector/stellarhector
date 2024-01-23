# Releases the CTF channels to all members
# Can be run from a ctf category channel
#   by an administrator or ctf operator
import core.bot as bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(name="release-ctf", description="Release the CTF to all members", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
async def release_ctf(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    ctf_category = interaction.channel.category

    member_role: discord.Role = discord.utils.get(interaction.guild.roles, name=bot.config.get("MEMBER_ROLE"))
    ctf_role: discord.Role = discord.utils.get(interaction.guild.roles, name=ctf_category.name)
    admin_role: discord.Role = discord.utils.get(interaction.guild.roles, name=bot.config.get("ADMIN_ROLE"))

    await ctf_category.edit(overwrites={
        interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False,view_channel=False,manage_channels=False),
        member_role: discord.PermissionOverwrite(read_messages=True,view_channel=True),
        ctf_role: discord.PermissionOverwrite(read_messages=True,view_channel=True),
        admin_role: discord.PermissionOverwrite(read_messages=True,view_channel=True,manage_channels=True)
    })

    channels = ctf_category.channels
    for channel in channels:
        await channel.edit(sync_permissions=True)

    await interaction.edit_original_response(content=f"Done; CTF released, welcome everyone! :wave:")

@release_ctf.error
async def error_on_release_ctf_command(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
