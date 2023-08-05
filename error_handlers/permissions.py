import discord
from discord import app_commands

async def check_role_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.errors.MissingRole):
        await interaction.response.send_message(":no_entry: Don't try, not allowed!", ephemeral=True)
        return True

    return False

