"""The scheduler that runs the bot's periodic jobs, and the watchdog that restarts the bot when it hangs."""

import asyncio
import calendar
import logging
import os
import threading
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as time_of_day
from typing import TypeVar
from zoneinfo import ZoneInfo

from discord.ext import tasks

import core.db as db
from utils.text import error_code

# Ticks don't fire at exactly the same second each time, so a job counts as due when its time is reached within this
# margin
TICK_SLACK = timedelta(minutes=1)

TICK_INTERVAL = timedelta(minutes=5)
DEFAULT_TIMEOUT = timedelta(minutes=4)
DEFAULT_WATCHDOG_LIMIT = timedelta(minutes=20)
# While a job runs, the runner beats this often, so a job's timeout may be longer than the watchdog limit
JOB_BEAT_INTERVAL = timedelta(minutes=1)
ALERT_TIMEOUT = timedelta(seconds=30)


log = logging.getLogger("bot")

Alert = Callable[[str], Awaitable[None]]
Heartbeat = Callable[[], None]
IsDue = Callable[[datetime, datetime | None], bool]
T = TypeVar("T")


async def _log_alert(message: str) -> None:
    log.warning(f"No alert channel set up, alert not posted: {message}")


@dataclass
class Job:
    """`run` should be a plain action that a slash command can call too. When `alert_after` is set, the admins are
    alerted once the job has kept failing for that long."""

    name: str
    is_due: IsDue
    run: Callable[[], Awaitable[object]]
    timeout: timedelta = DEFAULT_TIMEOUT
    alert_after: timedelta | None = None


@dataclass(frozen=True)
class JobState:
    last_run_at: datetime | None = None
    failing_since: datetime | None = None
    alerted: bool = False


class Scheduler:
    """Runs the registered jobs in one TickLoop that a Watchdog guards. Features register their jobs before `start`.
    `alert` posts a message for the admins about a job that keeps failing."""

    def __init__(self, watchdog_limit: timedelta = DEFAULT_WATCHDOG_LIMIT, alert: Alert = _log_alert) -> None:
        # Ticks are TICK_INTERVAL apart, so a shorter limit would kill a healthy bot
        if watchdog_limit <= TICK_INTERVAL:
            raise ValueError(f"Watchdog limit {watchdog_limit} must be longer than the tick interval {TICK_INTERVAL}")
        self.jobs: list[Job] = []
        self.watchdog_limit = watchdog_limit
        self.alert = alert
        self._tick_loop: TickLoop | None = None

    def register(self, job: Job) -> None:
        self.jobs.append(job)

    def start(self) -> None:
        # Called on every on_ready, which fires again after a reconnect
        if self._tick_loop is None:
            watchdog = Watchdog(self.watchdog_limit)
            watchdog.start()
            self._tick_loop = TickLoop(self.jobs, watchdog, alert=self.alert)
        self._tick_loop.start()


async def run_due_jobs(
    jobs: Iterable[Job], now: datetime, heartbeat: Heartbeat = lambda: None, alert: Alert = _log_alert
) -> None:
    """Run every due job once. A job that fails or times out is retried on the next tick. Once it has kept failing for
    its `alert_after`, the admins are alerted, and they are told again when it works."""
    for job in jobs:
        # Beat per job, not per tick: the jobs of one tick together may run longer than the watchdog limit
        heartbeat()
        state = _job_state(job.name)
        if not job.is_due(now, state.last_run_at):
            if state.last_run_at is None:
                # The first time a job is seen, it is recorded, so a daily or monthly job runs from its next slot on
                _set_last_run_at(job.name, now)
            continue

        try:
            await _beating_during(
                asyncio.wait_for(job.run(), timeout=job.timeout.total_seconds()), job.timeout, heartbeat
            )
        except Exception as error:
            log.exception(f"Scheduled job {job.name} failed (timeout {job.timeout})")
            await _record_failure(job, state, now, error, alert)
            continue

        # When the recovery can't be posted, it is tried again after the next successful run
        still_alerted = state.alerted and not await _post_alert(
            job, f":white_check_mark: Scheduled job `{job.name}` works again.", alert
        )
        _set_last_run_at(job.name, now, alerted=still_alerted)


async def _record_failure(job: Job, state: JobState, now: datetime, error: Exception, alert: Alert) -> None:
    failing_since = state.failing_since or now
    if state.failing_since is None:
        _set_failing_since(job.name, now)

    if job.alert_after is None or state.alerted or now - failing_since < job.alert_after:
        return

    message = (
        f":warning: Scheduled job `{job.name}` has been failing since <t:{int(failing_since.timestamp())}:f>"
        f" and is retried every tick. Last error: {error_code(error)}"
    )
    # An alert that couldn't be posted isn't marked as posted, so the next failing tick tries again
    if await _post_alert(job, message, alert):
        _set_alerted(job.name)


async def _post_alert(job: Job, message: str, alert: Alert) -> bool:
    try:
        await asyncio.wait_for(alert(message), timeout=ALERT_TIMEOUT.total_seconds())
    except Exception:
        log.exception(f"Could not post the alert for scheduled job {job.name}")
        return False
    return True


async def _beating_during(awaitable: Awaitable[T], timeout: timedelta, heartbeat: Heartbeat) -> T:
    """Await `awaitable` while calling `heartbeat` every JOB_BEAT_INTERVAL, for at most `timeout`.

    The beats stop after the timeout, so the watchdog still catches a job that swallows its cancellation and keeps the
    tick waiting. It also catches a blocked event loop, because no beats run then.
    """

    async def beat() -> None:
        beats = int(timeout / JOB_BEAT_INTERVAL)
        for _ in range(beats):
            await asyncio.sleep(JOB_BEAT_INTERVAL.total_seconds())
            heartbeat()

    beating = asyncio.create_task(beat())
    try:
        return await awaitable
    finally:
        beating.cancel()


def _job_state(name: str) -> JobState:
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT last_run_at, failing_since, alerted FROM job_runs WHERE name = ?", (name,)
        ).fetchone()
    if row is None:
        return JobState()
    return JobState(
        last_run_at=db.parse_time(row["last_run_at"]),
        failing_since=db.parse_time(row["failing_since"]),
        alerted=bool(row["alerted"]),
    )


def _set_last_run_at(name: str, when: datetime, alerted: bool = False) -> None:
    # A successful run ends the failure period
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO job_runs (name, last_run_at, alerted) VALUES (?, ?, ?) ON CONFLICT (name) DO UPDATE SET"
            " last_run_at = excluded.last_run_at, failing_since = NULL, alerted = excluded.alerted",
            (name, db.time_text(when), int(alerted)),
        )


def _set_failing_since(name: str, when: datetime) -> None:
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO job_runs (name, failing_since) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET failing_since = excluded.failing_since",
            (name, db.time_text(when)),
        )


def _set_alerted(name: str) -> None:
    with db.transaction() as conn:
        conn.execute("UPDATE job_runs SET alerted = 1 WHERE name = ?", (name,))


def every_minutes(minutes: int) -> IsDue:
    interval = timedelta(minutes=minutes)

    def is_due(now: datetime, last_run_at: datetime | None) -> bool:
        return last_run_at is None or now - last_run_at >= interval - TICK_SLACK

    return is_due


def daily_at(hh_mm: str, tz: str) -> IsDue:
    at = time_of_day.fromisoformat(hh_mm)
    zone = ZoneInfo(tz)

    def latest_slot(now: datetime) -> datetime:
        today = now.astimezone(zone).date()
        slot = datetime.combine(today, at, tzinfo=zone)
        if slot > now:
            slot = datetime.combine(today - timedelta(days=1), at, tzinfo=zone)
        return slot

    return _slot_is_due(latest_slot)


def monthly_on(day: int, hh_mm: str, tz: str) -> IsDue:
    at = time_of_day.fromisoformat(hh_mm)
    zone = ZoneInfo(tz)

    def slot_in(year: int, month: int) -> datetime:
        # A day past the end of the month, such as 31, means the last day of that month
        last_day = calendar.monthrange(year, month)[1]
        return datetime.combine(date(year, month, min(day, last_day)), at, tzinfo=zone)

    def latest_slot(now: datetime) -> datetime:
        local = now.astimezone(zone)
        slot = slot_in(local.year, local.month)
        if slot > now:
            previous = local.replace(day=1) - timedelta(days=1)
            slot = slot_in(previous.year, previous.month)
        return slot

    return _slot_is_due(latest_slot)


def _slot_is_due(latest_slot: Callable[[datetime], datetime]) -> IsDue:
    # A job that never ran waits for its next slot; the runner records when it first saw the job
    def is_due(now: datetime, last_run_at: datetime | None) -> bool:
        return last_run_at is not None and last_run_at < latest_slot(now)

    return is_due


def _hard_exit() -> None:
    # os._exit skips cleanup that could itself hang; Docker's restart policy brings the bot back
    os._exit(1)


class Watchdog:
    """Kills the process when the tick loop stops beating, for example because the event loop is blocked. It runs in
    a real thread, so it keeps working while the asyncio event loop is stuck."""

    CHECK_EVERY = timedelta(minutes=1)

    def __init__(
        self, limit: timedelta, clock: Callable[[], float] = time.monotonic, on_timeout: Callable[[], None] = _hard_exit
    ) -> None:
        self.limit = limit
        self.clock = clock
        self.on_timeout = on_timeout
        self.last_beat = clock()

    def beat(self) -> None:
        self.last_beat = self.clock()

    def check(self) -> None:
        silent_for = self.clock() - self.last_beat
        if silent_for > self.limit.total_seconds():
            log.critical(f"No scheduler heartbeat for {silent_for:.0f}s, exiting so Docker restarts the bot")
            self.on_timeout()

    def start(self) -> None:
        threading.Thread(target=self._watch, name="watchdog", daemon=True).start()

    def _watch(self) -> None:
        while True:
            time.sleep(self.CHECK_EVERY.total_seconds())
            self.check()


class TickLoop:
    def __init__(
        self,
        jobs: Iterable[Job],
        watchdog: Watchdog,
        interval: timedelta = TICK_INTERVAL,
        restart_delay: timedelta | None = None,
        alert: Alert = _log_alert,
    ) -> None:
        self.jobs = jobs
        self.alert = alert
        self.restart_delay = interval if restart_delay is None else restart_delay
        self.watchdog = watchdog
        self._loop = tasks.loop(seconds=interval.total_seconds())(self._tick)
        # discord.py types the handler as an unbound cog method; a bound method is called the same way
        self._loop.error(self._on_error)  # type: ignore[type-var]
        self._pending_restart: asyncio.TimerHandle | None = None

    def start(self) -> None:
        # on_ready fires again after a gateway reconnect, and the loop must only run once
        if not self._loop.is_running():
            self._loop.start()

    async def stop(self) -> None:
        if self._pending_restart is not None:
            self._pending_restart.cancel()
        self._loop.cancel()

    async def _on_error(self, error: BaseException) -> None:
        # tasks.loop stops for good after an uncaught exception, so it is started again once this run has ended. The
        # delay keeps a tick that keeps failing from spinning.
        log.error(f"Tick loop crashed, restarting in {self.restart_delay}", exc_info=error)
        task = self._loop.get_task()
        if task is not None:
            task.add_done_callback(self._restart_later)

    def _restart_later(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()  # Retrieving the logged exception stops asyncio from reporting it again
        self._pending_restart = asyncio.get_running_loop().call_later(self.restart_delay.total_seconds(), self.start)

    async def _tick(self) -> None:
        self.watchdog.beat()
        await run_due_jobs(self.jobs, datetime.now(UTC), heartbeat=self.watchdog.beat, alert=self.alert)
