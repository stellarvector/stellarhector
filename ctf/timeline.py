"""The automatic timeline of a CTF on CTFtime: which lifecycle steps still have to run, and when. The scheduled job
(`run`) and /ctf-status both use `plan`, so they always agree."""

import logging
from collections.abc import Awaitable, Callable, Coroutine, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Protocol

import discord

from ctf import store
from ctf.models import Ctf
from feeds.calendar.sessions import Session, linked_sessions
from feeds.ctftime_check import Record, stored_record
from utils.text import cut, error_code

log = logging.getLogger("bot")

# Discord names (the role "⚡ <name>", the category and the main channel) are at most 100 characters
NAME_LENGTH = 90

SETUP_NOTICE = (
    ":robot: Set up automatically, as a calendar session links to this CTF on CTFtime. The bot runs its "
    "next steps by itself: see `/ctf-status`."
)

# Posts in the CTF's #bot, or for the admins when the CTF is None
Notify = Callable[[Ctf | None, str], Awaitable[None]]
# (step, CTFtime ID) for a setup, (step, CTF ID) for the other steps
StepKey = tuple["Step", int]
# What a step posts once it worked: the CTF and the message for its #bot
Notice = tuple[Ctf, str] | None


class Step(Enum):
    # The value names the step in messages
    SETUP = "setup"
    LAST_CALL = "last call"
    RELEASE = "release"
    LOCK = "lock and archive"
    REMOVAL_REMINDER = "removal reminder"


@dataclass(frozen=True)
class Planned:
    step: Step
    # When the step is due
    at: datetime


class TimelineActions(Protocol):
    """The steps as the commands do them. Each but setup returns the notice to post in the CTF's #bot."""

    async def setup(self, ctftime_id: int, title: str) -> Ctf: ...

    async def last_call(self, ctf: Ctf, now: datetime) -> str: ...

    async def release(self, ctf: Ctf, now: datetime) -> str: ...

    async def lock(self, ctf: Ctf, now: datetime) -> str: ...


def plan_setup(start: datetime, finish: datetime, now: datetime) -> Planned | None:
    """A CTF linked from the calendar is set up 3 days before it starts. None once it is past its lock: there is
    nothing left to play or discuss then."""
    if now > _lock_at(finish):
        return None
    return Planned(Step.SETUP, start - timedelta(days=3))


def plan(ctf: Ctf, now: datetime) -> list[Planned]:
    """The steps still to run, in order; those with `at <= now` are due.

    From the CTF's start S and finish F: the last call at S - 1 day, the release at F + 1 day, the lock at F + 5 days
    and the removal reminder 4 weeks after the lock. Steps already done (also by command) are left out, as is a last
    call once S has passed or joining closed, and a release once the CTF is locked. A CTF without CTFtime dates, or
    that is removed, has no steps.
    """
    if ctf.ctftime_id is None or ctf.start is None or ctf.finish is None or ctf.removed_at is not None:
        return []

    lock = _lock_at(ctf.finish)
    steps = [
        (
            Step.LAST_CALL,
            ctf.start - timedelta(days=1),
            ctf.last_call_at is None and now < ctf.start and not ctf.joining_closed,
        ),
        (Step.RELEASE, ctf.finish + timedelta(days=1), ctf.released_at is None and ctf.locked_at is None),
        (Step.LOCK, lock, ctf.locked_at is None),
        (Step.REMOVAL_REMINDER, lock + timedelta(weeks=4), ctf.removal_reminded_at is None),
    ]
    return [Planned(step, at) for step, at, to_run in steps if to_run]


def _lock_at(finish: datetime) -> datetime:
    return finish + timedelta(days=5)


def is_manual(ctf: Ctf) -> bool:
    """A CTF without a CTFtime ID or dates gets no automatic steps."""
    return ctf.ctftime_id is None or ctf.start is None or ctf.finish is None


def next_step(ctf: Ctf, now: datetime) -> Planned | None:
    steps = plan(ctf, now)
    return steps[0] if steps else None


async def run(now: datetime, actions: TimelineActions, notify: Notify, told_failures: set[StepKey]) -> None:
    """Run every step that is due: first set up the CTFs linked from the calendar, then the steps of every CTF.

    A failing step is retried on every run, and the later steps of its CTF wait for it. Its failure is posted once
    until it works again; `told_failures` remembers which were posted.
    """
    for ctftime_id, record in _to_set_up():
        assert record.start is not None and record.finish is not None and record.title is not None
        planned = plan_setup(record.start, record.finish, now)
        if planned is None or planned.at > now:
            continue

        name = cut(record.title, NAME_LENGTH)
        await _attempt((Step.SETUP, ctftime_id), name, _setup(actions, ctftime_id, name), None, notify, told_failures)

    for ctf in store.managed():
        await _run_steps(ctf.id, now, actions, notify, told_failures)


async def _run_steps(
    ctf_id: int, now: datetime, actions: TimelineActions, notify: Notify, told_failures: set[StepKey]
) -> None:
    # Planned again after each step, since a step changes what is left (a lock leaves no release)
    ran: set[Step] = set()
    while True:
        ctf = store.reread(ctf_id)
        due = [planned.step for planned in plan(ctf, now) if planned.at <= now and planned.step not in ran]
        if not due:
            return
        step = due[0]
        ran.add(step)
        work = _run_step(step, ctf, now, actions, notify)
        if not await _attempt((step, ctf.id), ctf.name, work, ctf, notify, told_failures):
            return


async def _setup(actions: TimelineActions, ctftime_id: int, name: str) -> Notice:
    ctf = await actions.setup(ctftime_id, name)
    return ctf, SETUP_NOTICE


async def _run_step(step: Step, ctf: Ctf, now: datetime, actions: TimelineActions, notify: Notify) -> Notice:
    if step == Step.REMOVAL_REMINDER:
        await notify(None, _removal_reminder(ctf))
        store.mark_removal_reminded(ctf.id, now)
        return None
    action = {Step.LAST_CALL: actions.last_call, Step.RELEASE: actions.release, Step.LOCK: actions.lock}[step]
    try:
        return ctf, await action(ctf, now)
    except Exception:
        # A command did the same step at the same time (e.g. /release-ctf) and won: that is fine
        if step not in [planned.step for planned in plan(store.reread(ctf.id), now)]:
            log.info(f"The {step.value} of CTF {ctf.name!r} was done meanwhile")
            return None
        raise


async def _attempt(
    key: StepKey,
    name: str,
    work: Coroutine[Any, Any, Notice],
    ctf: Ctf | None,
    notify: Notify,
    told_failures: set[StepKey],
) -> bool:
    """Run the step and post its notice, or its failure unless that was posted before. Returns whether it worked."""
    step = key[0]
    try:
        notice = await work
    except Exception as error:
        log.exception(f"The automatic {step.value} of CTF {name!r} failed")
        if key in told_failures:
            return False
        message = (
            f":warning: The automatic {step.value} of **{discord.utils.escape_markdown(name)}** failed: "
            f"{error_code(error)}\nIt is tried again on every tick; this is only posted once."
        )
        try:
            await notify(ctf, message)
        except Exception:
            # Not remembered, so the next failure tries posting again
            log.exception(f"Could not post the failure of the automatic {step.value}")
            return False
        told_failures.add(key)
        return False

    told_failures.discard(key)
    log.info(f"Automatic {step.value} of CTF {name!r} done")
    if notice is not None:
        try:
            await notify(*notice)
        except Exception:
            # The step is done; only its notice is lost
            log.exception(f"Could not post the notice of the automatic {step.value} of CTF {name!r}")
    return True


def _removal_reminder(ctf: Ctf) -> str:
    message = (
        f":wastebasket: **{discord.utils.escape_markdown(ctf.name)}** finished over a month ago and is locked. "
        f"Remove it with `/remove-ctf` in <#{ctf.bot_channel_id}> when you're ready."
    )
    if ctf.archived_at is None:
        message += " It was not archived: run `/archive-ctf` there first."
    return message


def _to_set_up() -> Iterator[tuple[int, Record]]:
    """The CTFs linked from the calendar that were never set up and whose dates the CTFtime check knows."""
    for ctftime_id in linked_sessions():
        if store.ever_set_up(ctftime_id):
            continue
        record = stored_record(ctftime_id)
        if record is not None and not record.gone and record.start is not None:
            yield ctftime_id, record


def orphaned(sessions_before: dict[int, list[Session]], now: datetime) -> list[Ctf]:
    """The CTFs (not locked) whose calendar sessions all disappeared since `sessions_before` while one of them had not
    ended yet: they were cancelled or no longer link to the CTF. Sessions that merely ended don't count."""
    linked = linked_sessions()
    lost = [
        ctftime_id
        for ctftime_id, sessions in sessions_before.items()
        if ctftime_id not in linked and any(session.end > now for session in sessions)
    ]
    found = [store.find(ctftime_id=ctftime_id) for ctftime_id in lost]
    return [ctf for ctf in found if ctf is not None and ctf.locked_at is None]
