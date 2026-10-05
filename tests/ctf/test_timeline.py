import unittest
from datetime import timedelta

from core import db
from ctf import store, timeline
from ctf.timeline import Planned, Step, next_step, plan, plan_setup
from feeds import ctftime_check
from feeds.calendar.sessions import linked_sessions
from feeds.ctftime import Event
from tests.factories import (
    FINISH,
    LAST_CALL,
    LOCK,
    RELEASE,
    REMOVAL_REMINDER,
    START,
    new_ctf,
    stored_ctf,
    use_temporary_database,
    utc,
)
from tests.fakes import FakeCtftime
from tests.feeds.calendar.factories import store_session


class PlanTest(unittest.TestCase):
    def test_a_ctf_set_up_before_its_start_has_every_step_ahead_at_its_time(self):
        self.assertEqual(
            plan(stored_ctf(), utc(2026, 10, 7, 8)),
            [
                Planned(Step.LAST_CALL, LAST_CALL),
                Planned(Step.RELEASE, RELEASE),
                Planned(Step.LOCK, LOCK),
                Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER),
            ],
        )

    def test_steps_done_are_left_out(self):
        done = stored_ctf(last_call_at=LAST_CALL, released_at=RELEASE)

        self.assertEqual([planned.step for planned in plan(done, RELEASE)], [Step.LOCK, Step.REMOVAL_REMINDER])

    def test_a_step_done_early_by_command_is_left_out(self):
        released_early = stored_ctf(released_at=FINISH)

        self.assertNotIn(Step.RELEASE, [planned.step for planned in plan(released_early, FINISH)])

    def test_moved_dates_move_the_steps_still_to_run(self):
        moved = stored_ctf(start=START + timedelta(days=7), finish=FINISH + timedelta(days=7), last_call_at=LAST_CALL)

        self.assertEqual(
            plan(moved, utc(2026, 10, 9, 8)),
            [
                Planned(Step.RELEASE, RELEASE + timedelta(days=7)),
                Planned(Step.LOCK, LOCK + timedelta(days=7)),
                Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER + timedelta(days=7)),
            ],
        )

    def test_overdue_steps_are_all_due_in_order(self):
        due = [planned.step for planned in plan(stored_ctf(last_call_at=LAST_CALL), LOCK) if planned.at <= LOCK]

        self.assertEqual(due, [Step.RELEASE, Step.LOCK])

    def test_last_call_is_skipped_once_the_ctf_started(self):
        self.assertNotIn(Step.LAST_CALL, [planned.step for planned in plan(stored_ctf(), START)])

    def test_last_call_is_skipped_once_joining_closed_early_by_command(self):
        released_early = stored_ctf(released_at=START - timedelta(days=2))

        self.assertNotIn(Step.LAST_CALL, [planned.step for planned in plan(released_early, LAST_CALL)])

    def test_release_is_skipped_once_the_ctf_is_locked(self):
        locked = stored_ctf(last_call_at=LAST_CALL, locked_at=FINISH, archived_at=FINISH)

        self.assertEqual(plan(locked, FINISH), [Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER)])

    def test_lock_is_done_when_the_archive_failed(self):
        locked_not_archived = stored_ctf(last_call_at=LAST_CALL, released_at=RELEASE, locked_at=LOCK)

        self.assertEqual(plan(locked_not_archived, LOCK), [Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER)])

    def test_nothing_is_left_once_the_removal_reminder_was_sent(self):
        done = stored_ctf(
            last_call_at=LAST_CALL, released_at=RELEASE, locked_at=LOCK, removal_reminded_at=REMOVAL_REMINDER
        )

        self.assertEqual(plan(done, REMOVAL_REMINDER), [])

    def test_a_manual_ctf_has_no_steps(self):
        self.assertEqual(plan(stored_ctf(ctftime_id=None, start=None, finish=None), START), [])

    def test_a_removed_ctf_has_no_steps(self):
        self.assertEqual(plan(stored_ctf(removed_at=START), START), [])


class PlanSetupTest(unittest.TestCase):
    def test_setup_is_three_days_before_the_start(self):
        self.assertEqual(plan_setup(START, FINISH, utc(2026, 9, 1)), Planned(Step.SETUP, utc(2026, 10, 7, 8)))

    def test_setup_is_still_planned_until_five_days_after_the_finish(self):
        self.assertEqual(plan_setup(START, FINISH, LOCK), Planned(Step.SETUP, utc(2026, 10, 7, 8)))

    def test_no_setup_once_five_days_after_the_finish_passed(self):
        self.assertIsNone(plan_setup(START, FINISH, LOCK + timedelta(minutes=1)))


class NextStepTest(unittest.TestCase):
    def test_is_the_first_planned_step(self):
        self.assertEqual(next_step(stored_ctf(last_call_at=LAST_CALL), START), Planned(Step.RELEASE, RELEASE))

    def test_is_none_when_nothing_is_planned(self):
        self.assertIsNone(next_step(stored_ctf(ctftime_id=None, start=None, finish=None), START))


SETUP = START - timedelta(days=3)


def ctftime_event(ctftime_id=3352, title="Foo CTF 2026", start=START, finish=FINISH):
    return Event(
        id=ctftime_id,
        title=title,
        start=start,
        finish=finish,
        format="Jeopardy",
        weight=25.0,
        onsite=False,
        url="https://foo.example",
        ctftime_url=f"https://ctftime.org/event/{ctftime_id}/",
    )


class FakeActions:
    """Stands in for the lifecycle steps (the commands' functions): records them and stores them done as they do, or
    fails the steps in failing."""

    def __init__(self):
        self.done, self.failing = [], set()
        # The events on CTFtime, which setup takes the dates from
        self.events = {}

    def _do(self, step, name):
        self.done.append((step, name))
        if step in self.failing:
            raise RuntimeError(f"Discord refused the {step.value}")

    async def setup(self, ctftime_id, title):
        self._do(Step.SETUP, title)
        event = self.events[ctftime_id]
        return store.create(new_ctf(name=title, ctftime_id=ctftime_id, start=event.start, finish=event.finish))

    async def last_call(self, ctf, now):
        self._do(Step.LAST_CALL, ctf.name)
        store.mark_last_call(ctf.id, 9, 10, now)
        return "Last call posted."

    async def release(self, ctf, now):
        self._do(Step.RELEASE, ctf.name)
        store.mark_released(ctf.id, now)
        return "Released."

    async def lock(self, ctf, now):
        self._do(Step.LOCK, ctf.name)
        store.mark_locked(ctf.id, now)
        store.mark_archived(ctf.id, now)
        return "Locked and archived."


async def link_session(
    actions,
    uid="night",
    ctftime_id=3352,
    title="Foo CTF 2026",
    start=START,
    finish=FINISH,
    session_start=utc(2026, 10, 10, 17),
):
    """A calendar session linking to the CTFtime event, seen by the calendar sync and the daily CTFtime check, with the
    event on CTFtime for actions."""
    end = session_start + timedelta(hours=5)
    store_session(uid, session_start, end, "CTF night", f"https://ctftime.org/event/{ctftime_id}/")
    actions.events[ctftime_id] = ctftime_event(ctftime_id, title, start, finish)

    async def ignore_alert(ctftime_id, message):
        pass

    await ctftime_check.check(
        utc(2026, 9, 1),
        ignore_alert,
        store.ctftime_ids_not_locked(),
        store.set_dates,
        FakeCtftime(actions.events).get_event,
    )


class RunTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.actions = FakeActions()
        self.posted = []
        self.told = set()

    async def notify(self, ctf, message):
        """Where run posts: the CTF's #bot, or the admin channel for None."""
        self.posted.append((None if ctf is None else ctf.name, message))

    async def link_session(self, uid="night", **event):
        await link_session(self.actions, uid, **event)

    async def tick(self, now):
        await timeline.run(now, self.actions, self.notify, self.told)

    async def test_a_linked_ctf_is_set_up_three_days_before_its_start_named_after_its_ctftime_title(self):
        await self.link_session()

        await self.tick(SETUP - timedelta(minutes=5))
        self.assertEqual(self.actions.done, [])

        await self.tick(SETUP)
        self.assertEqual(self.actions.done, [(Step.SETUP, "Foo CTF 2026")])
        self.assertEqual(store.find(ctftime_id=3352).name, "Foo CTF 2026")

    async def test_two_sessions_of_the_same_ctf_lead_to_one_setup(self):
        await self.link_session("night-1")
        await self.link_session("night-2", session_start=utc(2026, 10, 11, 17))

        await self.tick(SETUP)
        await self.tick(SETUP + timedelta(minutes=5))

        self.assertEqual(self.actions.done, [(Step.SETUP, "Foo CTF 2026")])

    async def test_a_ctf_set_up_by_hand_with_the_ctftime_id_is_not_set_up_again(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        await self.link_session()

        await self.tick(SETUP)

        self.assertNotIn(Step.SETUP, [step for step, _ in self.actions.done])

    async def test_a_removed_ctf_is_not_set_up_again(self):
        store.mark_removed(store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH)).id, SETUP)
        await self.link_session()

        await self.tick(SETUP)

        self.assertEqual(self.actions.done, [])

    async def test_no_setup_once_five_days_after_the_finish_passed(self):
        await self.link_session()

        await self.tick(LOCK + timedelta(minutes=5))

        self.assertEqual(self.actions.done, [])

    async def test_each_step_runs_once_at_its_time(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))

        for now in (
            LAST_CALL - timedelta(minutes=5),
            LAST_CALL,
            LAST_CALL + timedelta(minutes=5),
            RELEASE,
            LOCK,
            LOCK + timedelta(minutes=5),
        ):
            await self.tick(now)

        self.assertEqual(self.actions.done, [(Step.LAST_CALL, "Foo"), (Step.RELEASE, "Foo"), (Step.LOCK, "Foo")])

    async def test_the_removal_reminder_is_posted_once_for_the_admins(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        await self.tick(LOCK)
        self.posted.clear()

        await self.tick(REMOVAL_REMINDER)
        await self.tick(REMOVAL_REMINDER + timedelta(minutes=5))

        self.assertEqual(len(self.posted), 1)
        where, message = self.posted[0]
        self.assertIsNone(where)
        self.assertIn("Foo", message)
        self.assertIn("/remove-ctf", message)
        self.assertEqual(store.find(ctftime_id=3352).removal_reminded_at, REMOVAL_REMINDER)

    async def test_a_failing_step_is_retried_every_tick_and_posted_once_in_the_ctfs_bot_channel(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        await self.tick(LAST_CALL)
        self.actions.failing.add(Step.RELEASE)
        self.posted.clear()

        await self.tick(RELEASE)
        await self.tick(RELEASE + timedelta(minutes=5))

        self.assertEqual(self.actions.done[1:], [(Step.RELEASE, "Foo"), (Step.RELEASE, "Foo")])
        self.assertEqual(len(self.posted), 1)
        where, message = self.posted[0]
        self.assertEqual(where, "Foo")
        self.assertIn("release", message)
        self.assertIn("Discord refused the release", message)

        self.actions.failing.clear()
        await self.tick(RELEASE + timedelta(minutes=10))
        self.assertIsNotNone(store.find(ctftime_id=3352).released_at)

    async def test_the_steps_after_a_failing_one_wait_for_it(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        self.actions.failing.add(Step.RELEASE)

        await self.tick(LOCK)

        self.assertEqual(self.actions.done, [(Step.RELEASE, "Foo")])

    async def test_a_failing_setup_is_posted_once_for_the_admins(self):
        await self.link_session()
        self.actions.failing.add(Step.SETUP)

        await self.tick(SETUP)
        await self.tick(SETUP + timedelta(minutes=5))

        self.assertEqual(self.actions.done, [(Step.SETUP, "Foo CTF 2026")] * 2)
        self.assertEqual(len(self.posted), 1)
        where, message = self.posted[0]
        self.assertIsNone(where)
        self.assertIn("Foo CTF 2026", message)

    async def test_each_step_done_is_noticed_in_the_ctfs_bot_channel(self):
        await self.link_session()

        await self.tick(SETUP)
        await self.tick(LAST_CALL)
        await self.tick(LOCK)

        self.assertEqual([where for where, _ in self.posted], ["Foo CTF 2026"] * 4)
        self.assertIn("automatic", self.posted[0][1].lower())
        self.assertEqual(
            [message for _, message in self.posted[1:]], ["Last call posted.", "Released.", "Locked and archived."]
        )

    async def test_a_notice_that_cannot_be_posted_does_not_fail_the_step(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))

        async def notices_fail(ctf, message):
            if "Last call posted." in message:
                raise RuntimeError("#bot is gone")
            await self.notify(ctf, message)

        await timeline.run(LAST_CALL, self.actions, notices_fail, self.told)

        self.assertEqual(self.actions.done, [(Step.LAST_CALL, "Foo")])
        self.assertEqual(self.posted, [])

    async def test_after_downtime_overdue_steps_catch_up_in_order_skipping_the_last_call_once_started(self):
        await self.link_session()

        await self.tick(RELEASE + timedelta(hours=2))

        self.assertEqual(self.actions.done, [(Step.SETUP, "Foo CTF 2026"), (Step.RELEASE, "Foo CTF 2026")])

    async def test_after_downtime_past_the_lock_release_and_lock_run_in_order(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))

        await self.tick(LOCK + timedelta(hours=2))

        self.assertEqual(self.actions.done, [(Step.RELEASE, "Foo"), (Step.LOCK, "Foo")])

    async def test_a_ctf_without_ctftime_id_gets_no_steps(self):
        store.create(new_ctf(name="Foo"))

        for now in (LAST_CALL, RELEASE, LOCK, REMOVAL_REMINDER):
            await self.tick(now)

        self.assertEqual((self.actions.done, self.posted), ([], []))

    async def test_dates_moved_on_ctftime_move_the_steps_still_to_run(self):
        await self.link_session()
        await self.tick(SETUP)
        week = timedelta(days=7)
        await self.link_session(start=START + week, finish=FINISH + week)

        await self.tick(LAST_CALL)
        self.assertEqual(self.actions.done, [(Step.SETUP, "Foo CTF 2026")])

        await self.tick(LAST_CALL + week)
        self.assertEqual(self.actions.done[1:], [(Step.LAST_CALL, "Foo CTF 2026")])

    async def test_a_step_done_by_a_command_meanwhile_is_no_failure(self):
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        await self.tick(LAST_CALL)
        self.posted.clear()

        async def released_by_command_meanwhile(ctf, now):
            store.mark_released(ctf.id, now)
            raise RuntimeError("Foo was already released, nothing changed.")

        self.actions.release = released_by_command_meanwhile
        await self.tick(RELEASE)

        self.assertEqual(self.posted, [])

    async def test_a_long_ctftime_title_is_cut_to_fit_discord_names(self):
        await self.link_session(title="A" * 150)

        await self.tick(SETUP)

        self.assertLessEqual(len(self.actions.done[0][1]), 90)


class OrphanedTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.actions = FakeActions()

    async def link_session(self, uid="night", **event):
        await link_session(self.actions, uid, **event)

    def forget(self, uid):
        """The calendar sync forgets the occurrence: cancelled, or over."""
        with db.transaction() as conn:
            conn.execute("DELETE FROM calendar_occurrences WHERE uid = ?", (uid,))

    async def test_a_ctf_whose_sessions_were_all_cancelled_is_orphaned(self):
        await self.link_session("night-1")
        await self.link_session("night-2", session_start=utc(2026, 10, 11, 17))
        ctf = store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        before = linked_sessions()

        self.forget("night-1")
        self.assertEqual(timeline.orphaned(before, utc(2026, 10, 9)), [])
        self.forget("night-2")
        self.assertEqual(timeline.orphaned(before, utc(2026, 10, 9)), [ctf])

    async def test_a_ctf_whose_last_session_is_over_is_not_orphaned(self):
        await self.link_session()
        store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH))
        before = linked_sessions()

        self.forget("night")

        self.assertEqual(timeline.orphaned(before, utc(2026, 10, 11)), [])

    async def test_sessions_of_a_ctf_not_set_up_orphan_nothing(self):
        await self.link_session()
        before = linked_sessions()

        self.forget("night")

        self.assertEqual(timeline.orphaned(before, utc(2026, 10, 9)), [])

    async def test_a_locked_ctf_is_not_orphaned(self):
        await self.link_session()
        store.mark_locked(store.create(new_ctf(name="Foo", ctftime_id=3352, start=START, finish=FINISH)).id, START)
        before = linked_sessions()

        self.forget("night")

        self.assertEqual(timeline.orphaned(before, utc(2026, 10, 9)), [])
