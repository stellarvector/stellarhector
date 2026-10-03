import unittest
from dataclasses import replace
from datetime import timedelta

from tests.test_ctfs import utc
from utils import ctfs
from utils.ctf_timeline import Planned, Step, next_step, plan

START, FINISH = utc(2026, 10, 10, 8), utc(2026, 10, 12, 18)
LAST_CALL, RELEASE, LOCK = START - timedelta(days=1), FINISH + timedelta(days=1), FINISH + timedelta(days=5)
REMOVAL_REMINDER = LOCK + timedelta(weeks=4)


def ctf(**changes):
    stored = ctfs.Ctf(name="Foo CTF", ctftime_id=3352, start=START, finish=FINISH, role_id=1, category_id=2,
                      main_channel_id=3, bot_channel_id=4, guide_message_id=5, id=1, join_channel_id=None,
                      join_message_id=None, overview_message_id=None, last_call_at=None, released_at=None,
                      locked_at=None, archived_at=None, removal_reminded_at=None, removed_at=None)
    return replace(stored, **changes)


class PlanTest(unittest.TestCase):
    def test_a_ctf_set_up_before_its_start_has_every_step_ahead_at_its_time(self):
        self.assertEqual(plan(ctf(), utc(2026, 10, 7, 8)), [
            Planned(Step.LAST_CALL, LAST_CALL),
            Planned(Step.RELEASE, RELEASE),
            Planned(Step.LOCK, LOCK),
            Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER),
        ])

    def test_steps_done_are_left_out(self):
        done = ctf(last_call_at=LAST_CALL, released_at=RELEASE)

        self.assertEqual([planned.step for planned in plan(done, RELEASE)], [Step.LOCK, Step.REMOVAL_REMINDER])

    def test_a_step_done_early_by_command_is_left_out(self):
        released_early = ctf(released_at=FINISH)

        self.assertNotIn(Step.RELEASE, [planned.step for planned in plan(released_early, FINISH)])

    def test_moved_dates_move_the_steps_still_to_run(self):
        moved = ctf(start=START + timedelta(days=7), finish=FINISH + timedelta(days=7), last_call_at=LAST_CALL)

        self.assertEqual(plan(moved, utc(2026, 10, 9, 8)), [
            Planned(Step.RELEASE, RELEASE + timedelta(days=7)),
            Planned(Step.LOCK, LOCK + timedelta(days=7)),
            Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER + timedelta(days=7)),
        ])

    def test_overdue_steps_are_all_due_in_order(self):
        due = [planned.step for planned in plan(ctf(last_call_at=LAST_CALL), LOCK) if planned.at <= LOCK]

        self.assertEqual(due, [Step.RELEASE, Step.LOCK])

    def test_last_call_is_skipped_once_the_ctf_started(self):
        self.assertNotIn(Step.LAST_CALL, [planned.step for planned in plan(ctf(), START)])

    def test_release_is_skipped_once_the_ctf_is_locked(self):
        locked = ctf(last_call_at=LAST_CALL, locked_at=FINISH, archived_at=FINISH)

        self.assertEqual(plan(locked, FINISH), [Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER)])

    def test_lock_is_done_when_the_archive_failed(self):
        locked_not_archived = ctf(last_call_at=LAST_CALL, released_at=RELEASE, locked_at=LOCK)

        self.assertEqual(plan(locked_not_archived, LOCK), [Planned(Step.REMOVAL_REMINDER, REMOVAL_REMINDER)])

    def test_nothing_is_left_once_the_removal_reminder_was_sent(self):
        done = ctf(last_call_at=LAST_CALL, released_at=RELEASE, locked_at=LOCK, removal_reminded_at=REMOVAL_REMINDER)

        self.assertEqual(plan(done, REMOVAL_REMINDER), [])

    def test_a_manual_ctf_has_no_steps(self):
        self.assertEqual(plan(ctf(ctftime_id=None, start=None, finish=None), START), [])

    def test_a_removed_ctf_has_no_steps(self):
        self.assertEqual(plan(ctf(removed_at=START), START), [])


class NextStepTest(unittest.TestCase):
    def test_is_the_first_planned_step(self):
        self.assertEqual(next_step(ctf(last_call_at=LAST_CALL), START), Planned(Step.RELEASE, RELEASE))

    def test_is_none_when_nothing_is_planned(self):
        self.assertIsNone(next_step(ctf(ctftime_id=None, start=None, finish=None), START))
