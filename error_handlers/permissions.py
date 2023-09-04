import discord
from discord import app_commands

async def check_role_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingRole) or isinstance(error, app_commands.errors.MissingAnyRole):
        await interaction.response.send_message(content=":no_entry: Don't try, not allowed!")
        return True

    return False

