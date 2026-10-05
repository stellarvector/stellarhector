"""CTFtime: the table of upcoming CTFs in #ctf-selection (/ctftime-table, and on the 1st of every month), and the
daily check of the CTFs' dates (/ctftime-check, and every day at 12:00)."""

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from bot import Hector
from cogs.replies import run_now
from core import checks
from core.scheduler import Job, daily_at, monthly_on
from ctf import store
from feeds import ctftime_check, ctftime_table
from feeds.ctftime import CtftimeError
from feeds.ctftime_check import CtftimeCheckResult
from utils.text import plural

log = logging.getLogger("bot")

DEFAULT_MONTHS = 2
# Every CTF is one CTFtime request of at most 30 seconds, so a handful of slow ones fit
CHECK_TIMEOUT = timedelta(minutes=10)


def check_reply(result: CtftimeCheckResult) -> str:
    text = f"CTFtime checked: {plural(result.checked, 'CTF')} checked, {plural(result.alerts, 'alert')} posted."
    if not result.skipped:
        return f":white_check_mark: {text}"
    return (
        f":warning: {text} {plural(result.skipped, 'CTF')} {'was' if result.skipped == 1 else 'were'} skipped"
        f" because CTFtime could not be reached; they are tried again on the next check."
    )


class CtftimeFeed(commands.Cog):
    def __init__(self, bot: Hector) -> None:
        self.bot = bot
        self.settings = bot.settings
        # The daily check and /ctftime-check take turns, so they never post the same alert twice
        self._check_lock = asyncio.Lock()

    async def cog_load(self) -> None:
        tz = self.settings.timezone
        self.bot.scheduler.register(
            Job("ctftime-check", daily_at("12:00", tz), self.check_ctftime, timeout=CHECK_TIMEOUT)
        )
        self.bot.scheduler.register(
            Job(
                "monthly-ctftime-table",
                monthly_on(1, "10:00", tz),
                self.post_monthly_table,
                alert_after=timedelta(days=1),
            )
        )

    def _today(self) -> date:
        return datetime.now(ZoneInfo(self.settings.timezone)).date()

    async def check_ctftime(self) -> CtftimeCheckResult:
        async with self._check_lock:
            result = await ctftime_check.check(
                datetime.now(UTC),
                self._alert,
                # Their dates move their automatic steps, also without a calendar session
                also_check=store.ctftime_ids_not_locked(),
                dates_changed=store.set_dates,
            )
        log.info(f"CTFtime check done: {result}")
        return result

    async def _alert(self, ctftime_id: int, message: str) -> None:
        # In the CTF's #bot once it is set up, else for the admins
        await self.bot.alert_ctf(store.find(ctftime_id=ctftime_id), message)

    async def post_monthly_table(self) -> None:
        channel_id = self.settings.channels.ctf_selection
        if channel_id is None:
            return

        start = ctftime_table.parse_start_month(None, self._today())
        channel = await self.bot.channel(channel_id)
        try:
            await ctftime_table.post_table(
                channel, start, DEFAULT_MONTHS, self.settings.timezone, hide_finished_at=datetime.now(UTC)
            )
        except discord.HTTPException as e:
            # Part of the table may be posted already, so a retry could post it twice: tell the admins instead
            log.error(f"Monthly CTFtime table could not be posted: {e}")
            await self.bot.try_alert_admins(
                f":warning: The monthly CTFtime table could not be (fully) posted in <#{channel_id}>, run "
                f"/ctftime-table to post it: {e}"
            )

    @app_commands.command(
        name="ctftime-check", description="Check the CTFs on the calendar for date changes on CTFtime right away"
    )
    @checks.admins_only()
    async def ctftime_check_command(self, interaction: discord.Interaction) -> None:
        result = await run_now(interaction, self.check_ctftime(), CHECK_TIMEOUT, "CTFtime check")
        if result is not None:
            await interaction.edit_original_response(content=check_reply(result))

    @app_commands.command(name="ctftime-table", description="Post the upcoming CTFs from CTFtime in #ctf-selection")
    @app_commands.rename(start_month="start-month")
    @app_commands.describe(
        start_month="First month, as 11 or 2026-11; when left out, this month without the CTFs that are over",
        months=f"How many months to list; {DEFAULT_MONTHS} when left out",
    )
    @checks.managers_only()
    async def ctftime_table_command(
        self,
        interaction: discord.Interaction,
        start_month: str | None = None,
        months: app_commands.Range[int, 1, 12] = DEFAULT_MONTHS,
    ) -> None:
        channel_id = self.settings.channels.ctf_selection
        if channel_id is None:
            await interaction.response.send_message(
                content=":warning: CTF_SELECTION_CHANNEL_ID is not configured, so there is nowhere to post the table.",
                ephemeral=True,
            )
            return

        try:
            start = ctftime_table.parse_start_month(start_month, self._today())
        except ValueError as e:
            await interaction.response.send_message(content=f":warning: {e}", ephemeral=True)
            return

        await interaction.response.defer(thinking=True, ephemeral=True)
        channel = await self.bot.channel(channel_id)
        try:
            # Without an explicit start, the finished CTFs are clutter; with one, the table shows history too
            hide_finished_at = datetime.now(UTC) if start_month is None else None
            count = await ctftime_table.post_table(
                channel, start, months, self.settings.timezone, hide_finished_at=hide_finished_at
            )
        except CtftimeError as e:
            log.warning(f"/ctftime-table could not reach CTFtime: {e}")
            await interaction.edit_original_response(
                content=":warning: CTFtime could not be reached, nothing was posted. Try again later."
            )
            return

        await interaction.edit_original_response(content=f"Done: {count} CTFs posted in <#{channel_id}>")
