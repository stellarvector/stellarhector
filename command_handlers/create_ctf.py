# Creates a ctf category/channel/role
# Can be run from any channel
#   by a management member or ctf operator
import bot
import discord
from discord import app_commands
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


@bot.client.tree.command(name="create-ctf", description="Create a new CTF", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("ADVISOR_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
@app_commands.describe(name="The CTF name")
async def create_ctf(interaction: discord.Interaction, name: str):
    await interaction.response.defer()
    message_id = interaction.channel.last_message_id

    admin_role: discord.Role = discord.utils.get(interaction.guild.roles, name=bot.config.get("ADMIN_ROLE"))
    member_role: discord.Role = discord.utils.get(interaction.guild.roles, name=bot.config.get("MEMBER_ROLE"))

    ctf_role = await create_ctf_role(interaction, "⚡ " + name, member_role)
    ctf_category = await create_ctf_category(interaction, "⚡ " + name, member_role, ctf_role, admin_role)
    ctf_main_channel = await create_ctf_main_channel(interaction, name, ctf_category)

    await interaction.followup.edit_message(message_id, content=f"Done: CTF boilerplate is set up :raised_hands:\nGo to the {ctf_main_channel.mention} channel to start adding challenges.")

async def create_ctf_role(interaction, name, member_role):
    role_color = discord.Color(int(bot.config.get("CTF_ROLE_COLOR_HEX"),16))
    ctf_role = await interaction.guild.create_role(
        name=name,
        color=role_color,
        mentionable=True
    )
    await ctf_role.edit(position=member_role.position + 1)

    return ctf_role

async def create_ctf_category(interaction, name, member_role, ctf_role, admin_role):
    ctf_category = await interaction.guild.create_category(
        name,
        overwrites={
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False,view_channel=False,manage_channels=False),
            member_role: discord.PermissionOverwrite(read_messages=True,view_channel=True),
            ctf_role: discord.PermissionOverwrite(read_messages=True,view_channel=True),
            admin_role: discord.PermissionOverwrite(read_messages=True,view_channel=True,manage_channels=True)
        },
    )
    await ctf_category.move(end=True)

    return ctf_category

async def create_ctf_main_channel(interaction, name, ctf_category):
    ctf_main_channel = await interaction.guild.create_text_channel(name, category=ctf_category)
    await ctf_main_channel.edit(sync_permissions=True, position=1)

    return ctf_main_channel

@create_ctf.error
async def error_on_create_ctf_command(interaction: discord.Interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
