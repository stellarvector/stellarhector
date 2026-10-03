"""The automatic timeline of a CTF on CTFtime: which lifecycle steps are still to run, and when, computed from its start
and finish and the steps done so far. The tick job that runs them (run) and /ctf-status both use plan, so they can't
disagree.
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

import discord

from utils import ctfs, ctftime_check
from utils.text import cut, inline_code

# How much of a failing step's error is posted
ERROR_LENGTH = 500
# How much of a CTFtime title an automatic setup names the CTF after: Discord names (of the role "⚡ <name>", the
# category and the main channel) are at most 100 characters
NAME_LENGTH = 90

SETUP_NOTICE = (":robot: Set up automatically, as a calendar session links to this CTF on CTFtime. The bot runs its "
                "next steps by itself: see `/ctf-status`.")

# The failing steps, (Step.SETUP, CTFtime ID) or (step, CTF ID), that were posted already: they are only posted again
# after they worked once. Kept in memory, so after a restart a step that still fails is posted once more.
_told = set()


class Step(Enum):
    """An automatic lifecycle step; the value names it for the user."""
    SETUP = "setup"
    LAST_CALL = "last call"
    RELEASE = "release"
    LOCK = "lock and archive"
    REMOVAL_REMINDER = "removal reminder"


@dataclass(frozen=True)
class Planned:
    """A step still to run, due from at on."""
    step: Step
    at: datetime


def plan_setup(start, finish, now):
    """When to set up a CTF on CTFtime from start to finish that has no ctfs row yet: 3 days before its start. None once
    it is past its lock (finish + 5 days), as there is nothing left to play or discuss then."""
    if now > _lock_at(finish):
        return None
    return Planned(Step.SETUP, start - timedelta(days=3))


def plan(ctf, now):
    """The steps still to run for the CTF (a ctfs.Ctf) at now, in the order to run them; those with at <= now are due.

    A step is due at a fixed time from the CTF's start S or finish F: last call at S - 1 day, release at F + 1 day, lock
    and archive at F + 5 days, the removal reminder 4 weeks after that. A step done already (also by command) is left
    out, and so are a last call once S has passed or joining closed (released or locked), and a release once the CTF
    is locked. A CTF without a CTFtime ID or dates (manual), or that is removed, has no steps.
    """
    if is_manual(ctf) or ctf.removed_at is not None:
        return []

    lock = _lock_at(ctf.finish)
    steps = [
        (Step.LAST_CALL, ctf.start - timedelta(days=1), ctf.last_call_at is None and now < ctf.start
                                                       and not ctf.joining_closed),
        (Step.RELEASE, ctf.finish + timedelta(days=1), ctf.released_at is None and ctf.locked_at is None),
        (Step.LOCK, lock, ctf.locked_at is None),
        (Step.REMOVAL_REMINDER, lock + timedelta(weeks=4), ctf.removal_reminded_at is None),
    ]
    return [Planned(step, at) for step, at, to_run in steps if to_run]


def _lock_at(finish):
    return finish + timedelta(days=5)


def is_manual(ctf):
    """Whether the CTF gets no automatic steps: it has no CTFtime ID, or no dates from it."""
    return ctf.ctftime_id is None or ctf.start is None or ctf.finish is None


def next_step(ctf, now):
    """The first step still to run for the CTF at now (see plan), or None when there is none."""
    steps = plan(ctf, now)
    return steps[0] if steps else None


async def run(now, actions, notify, told=_told):
    """Run every automatic step due at now, in order: set up the CTFs linked from a calendar session (plan_setup),
    then the steps of every CTF the bot manages (plan).

    actions does the steps, as the commands do: setup(ctftime_id, title) returns the new ctfs.Ctf, and last_call,
    release and lock (ctf, now) return the notice to post in the CTF's #bot. The removal reminder is posted by run
    itself, for the admins. notify(ctf, message) posts in the CTF's #bot, or for the admins when ctf is None.

    A step that fails is logged and tried again on the next run; the steps of its CTF after it wait for it. Its failure
    is posted once (in the CTF's #bot, or for the admins before setup), until it worked: told holds what was posted.
    """
    for ctftime_id, record in _to_set_up():
        planned = plan_setup(record.start, record.finish, now)
        if planned is None or planned.at > now:
            continue

        name = cut(record.title, NAME_LENGTH)

        async def setup():
            ctf = await actions.setup(ctftime_id, name)
            return ctf, SETUP_NOTICE
        await _attempt((Step.SETUP, ctftime_id), name, setup, None, notify, told)

    for ctf in ctfs.managed():
        await _run_steps(ctf.id, now, actions, notify, told)


async def _run_steps(ctf_id, now, actions, notify, told):
    """Run the CTF's due steps in order, planning again after each, since a step changes what is left (a lock leaves
    no release). Stops at a step that fails."""
    ran = set()
    while True:
        ctf = ctfs.get(ctf_id)
        due = [planned.step for planned in plan(ctf, now) if planned.at <= now and planned.step not in ran]
        if not due:
            return
        step = due[0]
        ran.add(step)

        async def run_step():
            if step == Step.REMOVAL_REMINDER:
                await notify(None, _removal_reminder(ctf))
                ctfs.mark_removal_reminded(ctf.id, now)
                return None
            action = {Step.LAST_CALL: actions.last_call, Step.RELEASE: actions.release, Step.LOCK: actions.lock}[step]
            try:
                return ctf, await action(ctf, now)
            except Exception:
                # A command did the step at the same time (e.g. /release-ctf), so it is refused here: that is fine
                if step not in [planned.step for planned in plan(ctfs.get(ctf.id), now)]:
                    logging.getLogger("bot").info(f"The {step.value} of CTF {ctf.name!r} was done meanwhile")
                    return None
                raise
        if not await _attempt((step, ctf.id), ctf.name, run_step, ctf, notify, told):
            return


async def _attempt(key, name, work, ctf, notify, told):
    """Await work(), the step key = (step, ID) of the CTF called name. Returns whether it worked. A failure is logged,
    and posted with notify(ctf, ...) unless key is in told already. work returns None, or the CTF and the notice to
    post in its #bot once it worked: a notice that can't be posted is only logged, the step is done."""
    step = key[0]
    try:
        done = await work()
    except Exception as error:
        logging.getLogger("bot").exception(f"The automatic {step.value} of CTF {name!r} failed")
        if key in told:
            return False
        message = (f":warning: The automatic {step.value} of **{discord.utils.escape_markdown(name)}** failed: "
                   f"{inline_code(f'{type(error).__name__}: {error}', ERROR_LENGTH)}\nIt is tried again on every "
                   f"tick; this is only posted once.")
        try:
            await notify(ctf, message)
        except Exception:
            # Not marked as told, so the next failure tries again
            logging.getLogger("bot").exception(f"Could not post the failure of the automatic {step.value}")
            return False
        told.add(key)
        return False

    told.discard(key)
    logging.getLogger("bot").info(f"Automatic {step.value} of CTF {name!r} done")
    if done is not None:
        try:
            await notify(*done)
        except Exception:
            logging.getLogger("bot").exception(f"Could not post the notice of the automatic {step.value} of CTF "
                                               f"{name!r}")
    return True


def _removal_reminder(ctf):
    message = (f":wastebasket: **{discord.utils.escape_markdown(ctf.name)}** finished over a month ago and is locked. "
               f"Remove it with `/remove-ctf` in <#{ctf.bot_channel_id}> when you're ready.")
    if ctf.archived_at is None:
        message += " It was not archived: run `/archive-ctf` there first."
    return message


def _to_set_up():
    """The CTFtime ID and ctftime_check.Record of every CTF linked from a calendar session that was never set up, and
    whose dates the daily CTFtime check knows."""
    for ctftime_id in ctftime_check.linked_sessions():
        if ctfs.ever_set_up(ctftime_id):
            continue
        record = ctftime_check.stored_record(ctftime_id)
        if record is not None and not record.gone and record.start is not None:
            yield ctftime_id, record


def orphaned(before, now):
    """The CTFs set up (and not removed or locked) whose calendar sessions are all gone since before, the
    ctftime_check.linked_sessions() of then, while one of them was not over at now: they were cancelled, or no longer
    link to the CTF. A CTF whose sessions are only over is not orphaned."""
    linked = ctftime_check.linked_sessions()
    lost = [ctftime_id for ctftime_id, sessions in before.items()
            if ctftime_id not in linked and any(session.end > now for session in sessions)]
    found = [ctfs.find(ctftime_id=ctftime_id) for ctftime_id in lost]
    return [ctf for ctf in found if ctf is not None and ctf.locked_at is None]
