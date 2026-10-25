"""Posting a CTF's credentials in its main channel (/post-credentials), typed in a form so they can span lines. They
are deleted again right before the CTF is released (see ctf/credentials.py)."""

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import ctf_or_refuse, guild, refuse
from core import checks
from core.errors import UNKNOWN_ERROR
from ctf import credentials, store
from ctf.credentials import CredentialsRefused
from ctf.location import Place

log = logging.getLogger("bot")

# Discord drops a command that isn't answered within 3 seconds, and a form can't be deferred: past this, the form opens
# empty
PREFILL_TIMEOUT = 2


class CredentialsForm(discord.ui.Modal, title="Post credentials"):
    def __init__(self, ctf_id: int, current: str | None) -> None:
        super().__init__()
        self.ctf_id = ctf_id
        self.text: discord.ui.TextInput[CredentialsForm] = discord.ui.TextInput(
            label="Instructions and credentials",
            style=discord.TextStyle.paragraph,
            default=current,
            max_length=credentials.TEXT_LIMIT,
        )
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await credentials.post_credentials(guild(interaction), store.reread(self.ctf_id), self.text.value)
        except CredentialsRefused as e:
            await interaction.followup.send(f":no_entry: {e}", ephemeral=True)
            return
        await interaction.followup.send(f"Credentials posted: {message.jump_url} :key:", ephemeral=True)

    # Modal's on_error, which discord.py types differently from the views' it overrides
    async def on_error(self, interaction: discord.Interaction, error: Exception, /) -> None:  # type: ignore[override]
        log.error("Posting credentials failed", exc_info=error)
        if interaction.response.is_done():
            await interaction.followup.send(UNKNOWN_ERROR, ephemeral=True)
        else:
            await interaction.response.send_message(UNKNOWN_ERROR, ephemeral=True)


class Credentials(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot

    @app_commands.command(
        name="post-credentials", description="Post the CTF's credentials, deleted again before the CTF is released"
    )
    @checks.staff_only()
    async def post_credentials_command(self, interaction: discord.Interaction) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT, Place.MAIN)
        if ctf is None:
            return
        # Also checked when the form is sent, but refused here it doesn't have to be filled in first
        if (reason := credentials.too_late(ctf)) is not None:
            await refuse(interaction, reason)
            return

        try:
            current = await asyncio.wait_for(credentials.current_credentials(guild(interaction), ctf), PREFILL_TIMEOUT)
        except TimeoutError:
            current = None
        await interaction.response.send_modal(CredentialsForm(ctf.id, current))
