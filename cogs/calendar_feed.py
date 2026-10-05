"""Mirrors the ICS calendar into the server's Discord events (every ICS_POLL_MINUTES, and with /calendar-sync), and
tells a CTF's #bot when all calendar sessions linking to it are gone. Switched off when ICS_URL is not set."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import cast

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import run_now
from core import checks
from core.scheduler import DEFAULT_TIMEOUT, Job, every_minutes
from ctf import timeline
from feeds.calendar import events
from feeds.calendar.events import SyncSummary
from feeds.calendar.sessions import linked_sessions

log = logging.getLogger("bot")

# Syncs failing in a row before the admins are alerted: 2.5 hours at the default interval
FAILURES_BEFORE_ALERT = 10

ORPHANED = (
    ":information_source: Every calendar session of this CTF was cancelled (or no longer links to it). The "
    "CTF is kept, and its automatic steps still run: remove it with `/remove-ctf` if it's not played."
)


class CalendarFeed(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot
        self.settings = bot.settings.calendar
        # The scheduled sync and /calendar-sync take turns, so they never create the same event twice
        self._lock = asyncio.Lock()

    async def cog_load(self) -> None:
        if self.settings.ics_url is None:
            return
        minutes = self.settings.poll_minutes
        self.bot.scheduler.register(
            Job(
                "calendar-sync",
                every_minutes(minutes),
                self.sync_calendar,
                alert_after=timedelta(minutes=minutes * FAILURES_BEFORE_ALERT),
            )
        )

    async def sync_calendar(self) -> SyncSummary:
        assert self.settings.ics_url is not None
        async with self._lock:
            guild = await self.bot.home_guild()
            channel_id = self.bot.settings.channels.calendar
            announce_channel = (
                None if channel_id is None else cast(discord.TextChannel, await self.bot.channel(channel_id))
            )

            sessions_before = linked_sessions()
            summary = await events.sync(
                guild,
                self.settings.ics_url,
                self.bot.settings.timezone,
                self.settings.lookahead,
                announce_channel,
                self._ping_role(guild),
            )
            log.info(f"Calendar sync done: {summary}")
            for ctf in timeline.orphaned(sessions_before, datetime.now(UTC)):
                try:
                    await self.bot.alert_ctf(ctf, ORPHANED)
                except Exception:
                    log.exception(f"Could not tell CTF {ctf.name!r} its calendar sessions are gone")
            return summary

    def _ping_role(self, guild: discord.Guild) -> discord.Role | None:
        name = self.settings.ping_role
        if name is None:
            return None
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            log.warning(f"ICS_PING_ROLE {name!r} is not a role on the server, announcing without a ping")
        return role

    @app_commands.command(name="calendar-sync", description="Sync the calendar into the Discord events right away")
    @checks.admins_only()
    async def calendar_sync_command(self, interaction: discord.Interaction) -> None:
        if self.settings.ics_url is None:
            await interaction.response.send_message(
                content=":warning: ICS_URL is not configured, so there is no calendar to sync.", ephemeral=True
            )
            return

        summary = await run_now(interaction, self.sync_calendar(), DEFAULT_TIMEOUT, "calendar sync")
        if summary is not None:
            await interaction.edit_original_response(
                content=f":white_check_mark: Calendar synced: {summary.created} created, {summary.updated} updated,"
                f" {summary.cancelled} cancelled."
            )
