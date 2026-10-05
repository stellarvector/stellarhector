"""/archive-channel: archiving a regular (non-CTF) channel to the archive repository."""

from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from archive.channel import archive_channel
from bot import Hector
from cogs.replies import guild
from core import checks
from ctf import store

CHOICE_TIMEOUT_SECONDS = 60


class OverwriteChoice(discord.ui.View):
    """Asks whoever archives a channel that was archived before whether to overwrite that archive or keep both."""

    def __init__(self, user: discord.abc.User) -> None:
        super().__init__(timeout=CHOICE_TIMEOUT_SECONDS)
        self.user = user
        self.overwrite: bool | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                content=":no_entry: Only the person archiving this channel can decide.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Overwrite", style=discord.ButtonStyle.danger)
    async def overwrite_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, True)

    @discord.ui.button(label="Keep both", style=discord.ButtonStyle.primary)
    async def keep_both_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self._choose(interaction, False)

    async def _choose(self, interaction: discord.Interaction, overwrite: bool) -> None:
        self.overwrite = overwrite
        await interaction.response.edit_message(
            content=f"Archiving ({'overwriting' if overwrite else 'keeping both'})...", view=None
        )
        self.stop()


class ChannelArchiving(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot

    @app_commands.command(name="archive-channel", description="Archive a regular (non-CTF) channel")
    @app_commands.describe(channel_id="The ID of the channel to archive")
    @checks.managers_only()
    async def archive_channel_command(self, interaction: discord.Interaction, channel_id: str) -> None:
        """The channel ID is a string because IDs exceed Discord's integer option range."""
        await interaction.response.defer(thinking=True)

        if not channel_id.strip().isdigit():
            await interaction.edit_original_response(content="That is not a valid channel ID.")
            return
        channel = guild(interaction).get_channel(int(channel_id))
        if not isinstance(channel, discord.TextChannel):
            await interaction.edit_original_response(content="That text channel does not exist.")
            return
        if channel.category_id is not None and store.find_by_category(channel.category_id) is not None:
            await interaction.edit_original_response(
                content=":no_entry: That is a CTF channel, use `/archive-ctf` instead."
            )
            return

        async def choose_overwrite(category: str, name: str) -> bool | None:
            view = OverwriteChoice(interaction.user)
            await interaction.edit_original_response(
                content=f":warning: {channel.mention} has already been archived. Overwrite the existing archive, "
                f"or keep both (the new archive gets a numbered suffix, e.g. `{category}/{name}-2`)?",
                view=view,
            )
            if await view.wait():
                return None
            return view.overwrite

        zone = ZoneInfo(self.bot.settings.timezone)
        archive = await archive_channel(channel, self.bot.archive_repository, zone, choose_overwrite)
        if archive is None:
            await interaction.edit_original_response(
                content=f"No choice was made, {channel.mention} was not archived.", view=None
            )
            return
        await interaction.edit_original_response(
            content=f"{interaction.user.mention} archived {channel.mention} as "
            f"`{archive.category}/{archive.archive_name}`"
        )
