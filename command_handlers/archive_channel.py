# Creates a backup of a regular (non-ctf) channel and its contents
# Can be run from any channel
#   by an administrator or ctf operator
import core.bot as bot
import discord
from discord import app_commands
from utils.archive.channel import ChannelArchive
from utils.archive.ctf import CtfArchive
from error_handlers.permissions import check_role_error
from error_handlers.default import default as default_error_handler


class ArchiveConflictView(discord.ui.View):
    def __init__(self, user: discord.abc.User):
        super().__init__(timeout=60)
        self.user = user
        self.overwrite = None

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(content=":no_entry: Only the person archiving this channel can decide.", ephemeral=True)
            return False

        return True

    @discord.ui.button(label="Overwrite", style=discord.ButtonStyle.danger)
    async def overwrite_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, True)

    @discord.ui.button(label="Keep both", style=discord.ButtonStyle.primary)
    async def keep_both_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.choose(interaction, False)

    async def choose(self, interaction: discord.Interaction, overwrite: bool):
        self.overwrite = overwrite
        await interaction.response.edit_message(content=f"Archiving ({'overwriting' if overwrite else 'keeping both'})...", view=None)
        self.stop()


@bot.client.tree.command(name="archive-channel", description="Archive a regular (non-CTF) channel", guild=bot.guild)
@app_commands.checks.has_any_role(
    bot.config.get("ADMIN_ROLE"),
    bot.config.get("CTF_OPERATOR_ROLE")
)
@app_commands.describe(channel_id="The ID of the channel to archive")
async def archive_channel(interaction: discord.Interaction, channel_id: str):
    await interaction.response.defer(thinking=True)

    # Channel IDs are passed as a string since they can exceed Discord's integer option range
    if not channel_id.strip().isdigit():
        await interaction.edit_original_response(content=f"That is not a valid channel ID.")
        return

    channel = interaction.guild.get_channel(int(channel_id))

    if not isinstance(channel, discord.TextChannel):
        await interaction.edit_original_response(content=f"That text channel does not exist.")
        return

    if channel.category and channel.category.name.startswith("⚡ "):
        await interaction.edit_original_response(content=f":no_entry: That is a CTF channel, use `/archive-ctf` instead.")
        return

    # Sync the archive repository so the check sees the latest archives
    _ = CtfArchive.get_archive_repository()

    overwrite = False
    if ChannelArchive.is_archived(channel.name):
        view = ArchiveConflictView(interaction.user)
        await interaction.edit_original_response(
            content=f":warning: {channel.mention} has already been archived. Overwrite the existing archive, or keep both (the new archive gets a numbered suffix, e.g. `{channel.name}-2`)?",
            view=view)

        if await view.wait():
            await interaction.edit_original_response(content=f"No choice was made, {channel.mention} was not archived.", view=None)
            return

        overwrite = view.overwrite

    archive = await ChannelArchive.init(channel)
    archive.generate_files(overwrite)
    archive.save()

    await interaction.edit_original_response(content=f"{interaction.user.mention} archived {channel.mention} as `{archive.archive_name}`")

@archive_channel.error
async def archive_channel_error(interaction, error):
    if await check_role_error(interaction, error):
        return

    await default_error_handler(interaction, error)
