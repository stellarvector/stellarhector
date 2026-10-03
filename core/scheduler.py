import asyncio
import calendar
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from datetime import time as time_of_day
from typing import Awaitable, Callable, Optional
from zoneinfo import ZoneInfo

from discord.ext import tasks

import core.db as db

# Ticks don't fire at exactly the same second each time, so a job counts as due
# when its time is reached within this margin
TICK_SLACK = timedelta(minutes=1)

TICK_INTERVAL = timedelta(minutes=5)
DEFAULT_TIMEOUT = timedelta(minutes=4)
DEFAULT_WATCHDOG_LIMIT = timedelta(minutes=20)

_jobs = []
_watchdog_limit = DEFAULT_WATCHDOG_LIMIT
_tick_loop = None


@dataclass
class Job:
    """When to run is decided by is_due; run should be a plain action that a slash command can call too.

    The timeout must stay below the watchdog limit, or a slow run gets the bot restarted.
    """
    name: str
    is_due: Callable[[datetime, Optional[datetime]], bool]
    run: Callable[[], Awaitable[None]]
    timeout: timedelta = DEFAULT_TIMEOUT


def register(job):
    _jobs.append(job)


def init(watchdog_limit=DEFAULT_WATCHDOG_LIMIT):
    global _watchdog_limit

    # Ticks are TICK_INTERVAL apart, so a shorter limit would kill a healthy bot
    if watchdog_limit <= TICK_INTERVAL:
        raise ValueError(f"Watchdog limit {watchdog_limit} must be longer than the tick interval {TICK_INTERVAL}")
    _watchdog_limit = watchdog_limit


def start():
    """Start the tick loop and the watchdog. Safe to call on every on_ready."""
    global _tick_loop

    if _tick_loop is None:
        watchdog = Watchdog(_watchdog_limit)
        watchdog.start()
        _tick_loop = TickLoop(_jobs, watchdog)
    _tick_loop.start()


async def run_due_jobs(jobs, now, heartbeat=lambda: None):
    """Run every due job once. A job that fails or times out is logged and retried next tick."""
    for job in jobs:
        # Beat per job, not per tick: the jobs of one tick together may run longer than the watchdog limit
        heartbeat()
        last_run_at = _last_run_at(job.name)
        if not job.is_due(now, last_run_at):
            if last_run_at is None:
                # First time we see this job: remember it so a daily/monthly job runs from its next slot on
                _set_last_run_at(job.name, now)
            continue

        try:
            # A job that swallows the cancellation keeps the tick waiting; the watchdog catches that case
            await asyncio.wait_for(job.run(), timeout=job.timeout.total_seconds())
        except Exception:
            logging.getLogger("bot").exception(f"Scheduled job {job.name} failed (timeout {job.timeout})")
            continue

        _set_last_run_at(job.name, now)


def _last_run_at(name):
    with db.transaction() as conn:
        row = conn.execute("SELECT last_run_at FROM job_runs WHERE name = ?", (name,)).fetchone()
    if row is None or row["last_run_at"] is None:
        return None
    return datetime.fromisoformat(row["last_run_at"])


def _set_last_run_at(name, when):
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO job_runs (name, last_run_at) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET last_run_at = excluded.last_run_at",
            (name, when.astimezone(timezone.utc).isoformat()),
        )


def every_minutes(minutes):
    interval = timedelta(minutes=minutes)

    def is_due(now, last_run_at):
        return last_run_at is None or now - last_run_at >= interval - TICK_SLACK

    return is_due


def daily_at(hh_mm, tz):
    at = time_of_day.fromisoformat(hh_mm)
    zone = ZoneInfo(tz)

    def latest_slot(now):
        today = now.astimezone(zone).date()
        slot = datetime.combine(today, at, tzinfo=zone)
        if slot > now:
            slot = datetime.combine(today - timedelta(days=1), at, tzinfo=zone)
        return slot

    return _slot_is_due(latest_slot)


def monthly_on(day, hh_mm, tz):
    """Day numbers past the end of a month (e.g. 31) mean the last day of that month."""
    at = time_of_day.fromisoformat(hh_mm)
    zone = ZoneInfo(tz)

    def slot_in(year, month):
        last_day = calendar.monthrange(year, month)[1]
        return datetime.combine(date(year, month, min(day, last_day)), at, tzinfo=zone)

    def latest_slot(now):
        local = now.astimezone(zone)
        slot = slot_in(local.year, local.month)
        if slot > now:
            previous = local.replace(day=1) - timedelta(days=1)
            slot = slot_in(previous.year, previous.month)
        return slot

    return _slot_is_due(latest_slot)


def _slot_is_due(latest_slot):
    # A job that never ran waits for its next slot; the runner records when it first saw the job
    def is_due(now, last_run_at):
        return last_run_at is not None and last_run_at < latest_slot(now)

    return is_due


def _hard_exit():
    # os._exit skips cleanup that could itself hang; Docker's restart policy brings the bot back
    os._exit(1)


class Watchdog:
    """Kills the process when the tick loop stops beating, e.g. because the event loop is blocked.

    It runs in a real thread so it keeps working while the asyncio event loop is stuck.
    """

    CHECK_EVERY = timedelta(minutes=1)

    def __init__(self, limit, clock=time.monotonic, on_timeout=_hard_exit):
        self.limit = limit
        self.clock = clock
        self.on_timeout = on_timeout
        self.last_beat = clock()

    def beat(self):
        self.last_beat = self.clock()

    def check(self):
        silent_for = self.clock() - self.last_beat
        if silent_for > self.limit.total_seconds():
            logging.getLogger("bot").critical(f"No scheduler heartbeat for {silent_for:.0f}s, exiting so Docker restarts the bot")
            self.on_timeout()

    def start(self):
        threading.Thread(target=self._watch, name="watchdog", daemon=True).start()

    def _watch(self):
        while True:
            time.sleep(self.CHECK_EVERY.total_seconds())
            self.check()


class TickLoop:
    """Wakes up every interval and runs the jobs that are due."""

    def __init__(self, jobs, watchdog, interval=TICK_INTERVAL, restart_delay=None):
        self.jobs = jobs
        self.restart_delay = interval if restart_delay is None else restart_delay
        self.watchdog = watchdog
        self._loop = tasks.loop(seconds=interval.total_seconds())(self._tick)
        self._loop.error(self._on_error)
        self._pending_restart = None

    def start(self):
        # on_ready fires again after a gateway reconnect, the loop must only run once
        if not self._loop.is_running():
            self._loop.start()

    async def stop(self):
        if self._pending_restart is not None:
            self._pending_restart.cancel()
        self._loop.cancel()

    async def _on_error(self, error):
        # tasks.loop stops for good after an uncaught exception, so start it again once this run has ended.
        # Waiting first keeps a tick that keeps failing from spinning.
        logging.getLogger("bot").error(f"Tick loop crashed, restarting in {self.restart_delay}", exc_info=error)
        self._loop.get_task().add_done_callback(self._restart_later)

    def _restart_later(self, task):
        if not task.cancelled():
            task.exception()  # already logged above; stops asyncio from reporting it again
        self._pending_restart = asyncio.get_running_loop().call_later(self.restart_delay.total_seconds(), self.start)

    async def _tick(self):
        self.watchdog.beat()
        await run_due_jobs(self.jobs, datetime.now(timezone.utc), heartbeat=self.watchdog.beat)
