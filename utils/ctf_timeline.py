"""The automatic timeline of a CTF on CTFtime: which lifecycle steps are still to run, and when, computed from its start
and finish and the steps done so far. The tick job that runs them and /ctf-status both use plan, so they can't disagree.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class Step(Enum):
    """An automatic lifecycle step; the value names it for the user."""
    LAST_CALL = "last call"
    RELEASE = "release"
    LOCK = "lock and archive"
    REMOVAL_REMINDER = "removal reminder"


@dataclass(frozen=True)
class Planned:
    """A step still to run, due from at on."""
    step: Step
    at: datetime


def plan(ctf, now):
    """The steps still to run for the CTF (a ctfs.Ctf) at now, in the order to run them; those with at <= now are due.

    A step is due at a fixed time from the CTF's start S or finish F: last call at S - 1 day, release at F + 1 day, lock
    and archive at F + 5 days, the removal reminder 4 weeks after that. A step done already (also by command) is left
    out, and so are a last call once S has passed and a release once the CTF is locked. A CTF without a CTFtime ID or
    dates (manual), or that is removed, has no steps.
    """
    if is_manual(ctf) or ctf.removed_at is not None:
        return []

    lock = ctf.finish + timedelta(days=5)
    steps = [
        (Step.LAST_CALL, ctf.start - timedelta(days=1), ctf.last_call_at is None and now < ctf.start),
        (Step.RELEASE, ctf.finish + timedelta(days=1), ctf.released_at is None and ctf.locked_at is None),
        (Step.LOCK, lock, ctf.locked_at is None),
        (Step.REMOVAL_REMINDER, lock + timedelta(weeks=4), ctf.removal_reminded_at is None),
    ]
    return [Planned(step, at) for step, at, to_run in steps if to_run]


def is_manual(ctf):
    """Whether the CTF gets no automatic steps: it has no CTFtime ID, or no dates from it."""
    return ctf.ctftime_id is None or ctf.start is None or ctf.finish is None


def next_step(ctf, now):
    """The first step still to run for the CTF at now (see plan), or None when there is none."""
    steps = plan(ctf, now)
    return steps[0] if steps else None
