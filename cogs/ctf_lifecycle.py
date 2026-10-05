"""Setting up, releasing, locking, archiving and removing CTFs, by command and by the automatic timeline, and
/ctf-status. All but /setup-ctf and /ctf-status run in the CTF's #bot channel."""

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import ctf_or_refuse, guild, reply_after_long_work
from core import checks
from core.scheduler import Job, every_minutes
from ctf import status, store, timeline
from ctf.archive import archive_ctf
from ctf.join_message import LastCallRefused, post_last_call
from ctf.location import Place
from ctf.lock import Locked, LockRefused, lock_ctf
from ctf.models import Ctf
from ctf.release import ReleaseRefused, release_ctf
from ctf.remove import remove_ctf
from ctf.setup import SetupRefused, setup_ctf
from utils.text import error_code

log = logging.getLogger("bot")

# Locking archives the CTF, git push included, which can take a while; stopping it halfway leaves it unarchived
TIMELINE_TIMEOUT = timedelta(minutes=30)
TIMELINE_MINUTES = 5


def lock_notice(locked: Locked) -> str:
    if locked.archive_error is None:
        return "Locked and archived. Remove it with `/remove-ctf` when you're ready."
    return (
        f":warning: Locked, but archiving failed: {error_code(locked.archive_error)}\nRun `/archive-ctf` to try again."
    )


class CtfLifecycle(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot
        self.settings = bot.settings
        self._told_timeline_failures: set[timeline.StepKey] = set()

    async def cog_load(self) -> None:
        self.bot.scheduler.register(
            Job("ctf-timeline", every_minutes(TIMELINE_MINUTES), self.run_timeline, timeout=TIMELINE_TIMEOUT)
        )

    async def archive(self, guild: discord.Guild, ctf: Ctf, now: datetime) -> None:
        await archive_ctf(guild, ctf, now, self.bot.archive_repository, ZoneInfo(self.settings.timezone))

    async def run_timeline(self) -> None:
        guild = await self.bot.home_guild()
        actions = TimelineActions(self, guild)
        await timeline.run(datetime.now(UTC), actions, self.bot.alert_ctf, self._told_timeline_failures)

    @app_commands.command(name="setup-ctf", description="Set up a new CTF")
    @app_commands.rename(ctftime_id="ctftime-id")
    @app_commands.describe(
        name="The CTF name", ctftime_id="The CTF's event ID on CTFtime, for its dates and the automatic timeline"
    )
    @checks.managers_only()
    async def setup_ctf_command(
        self, interaction: discord.Interaction, name: str, ctftime_id: int | None = None
    ) -> None:
        await interaction.response.defer(thinking=True)
        try:
            ctf = await setup_ctf(guild(interaction), name, ctftime_id, self.settings)
        except SetupRefused as e:
            await interaction.edit_original_response(content=f":no_entry: {e}")
            return

        await interaction.edit_original_response(
            content=f"Done: CTF is set up :raised_hands:\n"
            f"Go to the <#{ctf.main_channel_id}> channel to start adding challenges."
        )

    @app_commands.command(name="last-call", description="Post the CTF's join message again as a last call")
    @checks.staff_only()
    async def last_call_command(self, interaction: discord.Interaction) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        await interaction.response.defer(thinking=True)
        try:
            ctf = await post_last_call(guild(interaction), ctf, self.settings.channels.upcoming_ctfs, datetime.now(UTC))
        except LastCallRefused as e:
            await interaction.edit_original_response(content=f":no_entry: {e}")
            return

        await interaction.edit_original_response(
            content=f"Done: last call posted in <#{ctf.join_channel_id}> :rotating_light:"
        )

    @app_commands.command(name="release-ctf", description="Release the CTF to all members")
    @checks.managers_only()
    async def release_ctf_command(self, interaction: discord.Interaction) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        await interaction.response.defer(thinking=True)
        try:
            await release_ctf(guild(interaction), ctf, self.settings.roles, datetime.now(UTC))
        except ReleaseRefused as e:
            await interaction.edit_original_response(content=f":no_entry: {e}")
            return

        await interaction.edit_original_response(content="Done; CTF released, welcome everyone! :wave:")

    @app_commands.command(name="lock-ctf", description="Make the CTF read-only and archive it")
    @checks.managers_only()
    async def lock_ctf_command(self, interaction: discord.Interaction) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        await interaction.response.defer(thinking=True)
        try:
            locked = await lock_ctf(guild(interaction), ctf, self.settings.roles, datetime.now(UTC), self.archive)
        except LockRefused as e:
            await interaction.edit_original_response(content=f":no_entry: {e}")
            return

        await reply_after_long_work(interaction, lock_notice(locked))

    @app_commands.command(name="archive-ctf", description="Archive a CTF")
    @checks.managers_only()
    async def archive_ctf_command(self, interaction: discord.Interaction) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        await interaction.response.defer(thinking=True)
        await self.archive(guild(interaction), ctf, datetime.now(UTC))
        await reply_after_long_work(interaction, f"{interaction.user.mention} archived {ctf.name}")

    @app_commands.command(name="remove-ctf", description="Remove a CTF (PERMANENTLY)")
    @app_commands.describe(force="Also remove it when it was never archived")
    @checks.managers_only()
    async def remove_ctf_command(self, interaction: discord.Interaction, force: bool = False) -> None:
        ctf = await ctf_or_refuse(interaction, Place.BOT)
        if ctf is None:
            return

        if ctf.archived_at is None and not force:
            await interaction.response.send_message(
                content=":no_entry: I refuse to remove this CTF because it was never archived. "
                "Run `/archive-ctf` first."
            )
            return

        await interaction.response.send_message(content=f"Removing {ctf.name}...")
        removal = await remove_ctf(guild(interaction), ctf, datetime.now(UTC))
        not_deleted = ", ".join(removal.not_deleted)
        if not removal.removed:
            await interaction.edit_original_response(
                content=f":warning: These could not be deleted: {not_deleted}\n"
                "Delete them by hand or run `/remove-ctf` again."
            )
            return

        # This channel is deleted now, so the admins are told in the admin channel
        message = f"{interaction.user.mention} removed the CTF {ctf.name}"
        if removal.not_deleted:
            message += f"\n:warning: These could not be deleted, delete them by hand: {not_deleted}"
        await self.bot.alert_admins(message)

    @app_commands.command(name="ctf-status", description="Show the CTFs the bot manages and what happens next")
    @checks.staff_only()
    async def ctf_status_command(self, interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        entries = [(ctf, store.players(ctf.id)) for ctf in store.managed()]
        first, *rest = status.report(entries, interaction.guild_id, datetime.now(UTC))

        await interaction.response.send_message(first, ephemeral=True)
        for message in rest:
            await interaction.followup.send(message, ephemeral=True)


class TimelineActions:
    """The automatic steps, done with the same functions as the commands."""

    def __init__(self, cog: CtfLifecycle, guild: discord.Guild) -> None:
        self.cog = cog
        self.guild = guild

    async def setup(self, ctftime_id: int, title: str) -> Ctf:
        return await setup_ctf(self.guild, title, ctftime_id, self.cog.settings)

    async def last_call(self, ctf: Ctf, now: datetime) -> str:
        ctf = await post_last_call(self.guild, ctf, self.cog.settings.channels.upcoming_ctfs, now)
        return f":robot: Automatic last call: the join message is posted again in <#{ctf.join_channel_id}>."

    async def release(self, ctf: Ctf, now: datetime) -> str:
        await release_ctf(self.guild, ctf, self.cog.settings.roles, now)
        return ":robot: Released automatically: every member can read and write in the CTF now, and joining is closed."

    async def lock(self, ctf: Ctf, now: datetime) -> str:
        locked = await lock_ctf(self.guild, ctf, self.cog.settings.roles, now, self.cog.archive)
        return f":robot: Automatic lock: {lock_notice(locked)}"
