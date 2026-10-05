import logging

import discord
from discord import app_commands

log = logging.getLogger("bot")

NOT_ALLOWED = ":no_entry: Don't try, not allowed!"
UNKNOWN_ERROR = "Sorry, an unknown error occurred, please ask an admin for help."


async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    # A missing role gets a refusal; anything else is logged and gets an apology
    if isinstance(error, (app_commands.MissingRole, app_commands.MissingAnyRole)):
        await _reply(interaction, NOT_ALLOWED)
        return

    command = interaction.command.name if interaction.command is not None else "?"
    log.error(f"Command /{command} failed: {error}", exc_info=error)
    await _reply(interaction, UNKNOWN_ERROR)


async def _reply(interaction: discord.Interaction, content: str) -> None:
    # A deferred interaction can't be responded to again
    if interaction.response.is_done():
        await interaction.followup.send(content=content)
    else:
        await interaction.response.send_message(content=content)
