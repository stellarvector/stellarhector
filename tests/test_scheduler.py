import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from core import db, scheduler


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


class EveryMinutesTest(unittest.TestCase):
    def test_first_run_ever_is_due(self):
        self.assertTrue(scheduler.every_minutes(15)(utc(2026, 10, 3, 12, 0), None))

    def test_due_once_the_interval_has_passed(self):
        is_due = scheduler.every_minutes(15)
        last = utc(2026, 10, 3, 12, 0)

        self.assertFalse(is_due(utc(2026, 10, 3, 12, 10), last))
        self.assertTrue(is_due(utc(2026, 10, 3, 12, 15), last))

    def test_tick_slightly_early_still_counts(self):
        is_due = scheduler.every_minutes(15)
        last = utc(2026, 10, 3, 12, 0, 1)

        self.assertTrue(is_due(utc(2026, 10, 3, 12, 15, 0), last))


BRUSSELS = "Europe/Brussels"


class DailyAtTest(unittest.TestCase):
    def test_due_at_first_tick_after_the_time(self):
        is_due = scheduler.daily_at("09:00", BRUSSELS)
        last = utc(2026, 10, 2, 7, 0)  # 09:00 Brussels (CEST, UTC+2)

        self.assertFalse(is_due(utc(2026, 10, 3, 6, 55), last))
        self.assertTrue(is_due(utc(2026, 10, 3, 7, 3), last))

    def test_not_due_again_on_the_same_day(self):
        is_due = scheduler.daily_at("09:00", BRUSSELS)
        last = utc(2026, 10, 3, 7, 3)

        self.assertFalse(is_due(utc(2026, 10, 3, 7, 8), last))
        self.assertFalse(is_due(utc(2026, 10, 3, 21, 55), last))

    def test_first_run_ever_waits_for_the_slot(self):
        is_due = scheduler.daily_at("09:00", BRUSSELS)

        self.assertFalse(is_due(utc(2026, 10, 3, 12, 0), None))

    def test_down_over_the_slot_runs_once(self):
        is_due = scheduler.daily_at("09:00", BRUSSELS)
        last = utc(2026, 9, 30, 7, 0)
        back_up = utc(2026, 10, 3, 12, 0)

        self.assertTrue(is_due(back_up, last))
        self.assertFalse(is_due(back_up + timedelta(minutes=5), back_up))

    def test_keeps_local_time_across_dst_change(self):
        is_due = scheduler.daily_at("09:00", BRUSSELS)
        # 2026-10-25: CEST (UTC+2) -> CET (UTC+1), so 09:00 local is 08:00 UTC
        last = utc(2026, 10, 24, 7, 0)

        self.assertFalse(is_due(utc(2026, 10, 25, 7, 30), last))
        self.assertTrue(is_due(utc(2026, 10, 25, 8, 0), last))

    def test_time_skipped_by_dst_runs_once_that_day(self):
        is_due = scheduler.daily_at("02:30", BRUSSELS)
        # 2026-03-29: 02:00 CET jumps to 03:00 CEST, so 02:30 does not exist
        last = utc(2026, 3, 28, 1, 30)
        ran = utc(2026, 3, 29, 1, 35)

        self.assertTrue(is_due(ran, last))
        self.assertFalse(is_due(utc(2026, 3, 29, 21, 0), ran))

    def test_time_repeated_by_dst_runs_once_that_day(self):
        is_due = scheduler.daily_at("02:30", BRUSSELS)
        # 2026-10-25: 03:00 CEST falls back to 02:00 CET, so 02:30 happens twice
        last = utc(2026, 10, 24, 0, 30)
        ran = utc(2026, 10, 25, 0, 30)

        self.assertTrue(is_due(ran, last))
        self.assertFalse(is_due(utc(2026, 10, 25, 1, 30), ran))


class MonthlyOnTest(unittest.TestCase):
    def test_due_at_first_tick_after_the_day_and_time(self):
        is_due = scheduler.monthly_on(1, "10:00", BRUSSELS)
        last = utc(2026, 10, 1, 8, 0)  # 10:00 Brussels (CEST)

        self.assertFalse(is_due(utc(2026, 10, 31, 22, 55), last))
        self.assertTrue(is_due(utc(2026, 11, 1, 9, 2), last))  # 10:00 CET is 09:00 UTC

    def test_not_due_again_in_the_same_month(self):
        is_due = scheduler.monthly_on(1, "10:00", BRUSSELS)
        last = utc(2026, 11, 1, 9, 2)

        self.assertFalse(is_due(utc(2026, 11, 30, 22, 55), last))

    def test_first_run_ever_waits_for_the_slot(self):
        is_due = scheduler.monthly_on(1, "10:00", BRUSSELS)

        self.assertFalse(is_due(utc(2026, 10, 3, 12, 0), None))

    def test_down_over_the_slot_runs_once(self):
        is_due = scheduler.monthly_on(1, "10:00", BRUSSELS)
        last = utc(2026, 8, 1, 8, 0)
        back_up = utc(2026, 10, 3, 12, 0)

        self.assertTrue(is_due(back_up, last))
        self.assertFalse(is_due(back_up + timedelta(minutes=5), back_up))

    def test_day_past_month_end_means_last_day(self):
        is_due = scheduler.monthly_on(31, "10:00", BRUSSELS)
        last = utc(2027, 1, 31, 9, 0)

        self.assertFalse(is_due(utc(2027, 2, 28, 8, 55), last))
        self.assertTrue(is_due(utc(2027, 2, 28, 9, 0), last))

    def test_keeps_local_time_across_dst_change(self):
        is_due = scheduler.monthly_on(1, "00:30", BRUSSELS)
        # 00:30 on 1 November is 23:30 UTC the day before (CET); on 1 October it was 22:30 UTC (CEST)
        last = utc(2026, 9, 30, 22, 30)

        self.assertFalse(is_due(utc(2026, 10, 31, 22, 30), last))
        self.assertTrue(is_due(utc(2026, 10, 31, 23, 30), last))


def always_due(now, last_run_at):
    return True


def use_temporary_database(test):
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    path = Path(tmp.name) / "test.db"
    db.init(path)
    test.addCleanup(db.close)
    return path


class RunDueJobsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db_path = use_temporary_database(self)
        self.calls = []

    def job(self, name, is_due=always_due, fail=False, **kwargs):
        async def run():
            self.calls.append(name)
            if fail:
                raise RuntimeError(f"{name} failed")

        return scheduler.Job(name, is_due, run, **kwargs)

    async def test_failing_job_does_not_stop_others_and_is_retried(self):
        jobs = [self.job("broken", is_due=scheduler.every_minutes(60), fail=True),
                self.job("fine", is_due=scheduler.every_minutes(60))]

        with self.assertLogs("bot", level="ERROR") as logs:
            await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 12, 0))
            await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 12, 5))

        self.assertEqual(self.calls, ["broken", "fine", "broken"])
        self.assertIn("RuntimeError: broken failed", "\n".join(logs.output))

    async def test_hanging_job_is_cancelled_and_others_still_run(self):
        cancelled = []

        async def hang():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                cancelled.append("hang")
                raise

        jobs = [scheduler.Job("hang", always_due, hang, timeout=timedelta(milliseconds=50)),
                self.job("fine")]

        with self.assertLogs("bot", level="ERROR") as logs:
            await asyncio.wait_for(scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 12, 0)), timeout=5)

        self.assertEqual(cancelled, ["hang"])
        self.assertEqual(self.calls, ["fine"])
        self.assertIn("TimeoutError", "\n".join(logs.output))

    async def test_new_daily_job_waits_for_its_first_slot(self):
        jobs = [self.job("daily", is_due=scheduler.daily_at("09:00", BRUSSELS))]

        await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 12, 0))
        await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 12, 5))
        self.assertEqual(self.calls, [])

        await scheduler.run_due_jobs(jobs, utc(2026, 10, 4, 7, 0))
        self.assertEqual(self.calls, ["daily"])

    async def test_daily_job_does_not_run_again_after_restart(self):
        jobs = [self.job("daily", is_due=scheduler.daily_at("09:00", BRUSSELS))]
        await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 6, 55))
        await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 7, 0))

        db.close()
        db.init(self.db_path)
        await scheduler.run_due_jobs(jobs, utc(2026, 10, 3, 7, 5))

        self.assertEqual(self.calls, ["daily"])

    async def test_heartbeat_before_each_job(self):
        events = []

        def job(name):
            async def run():
                events.append(name)

            return scheduler.Job(name, always_due, run)

        await scheduler.run_due_jobs([job("a"), job("b")], utc(2026, 10, 3, 12, 0),
                                     heartbeat=lambda: events.append("beat"))

        self.assertEqual(events, ["beat", "a", "beat", "b"])

    async def test_keeps_beating_while_a_long_job_runs(self):
        beats = []

        async def slow():
            await asyncio.sleep(0.35)

        original = scheduler.JOB_BEAT_INTERVAL
        scheduler.JOB_BEAT_INTERVAL = timedelta(seconds=0.1)
        self.addCleanup(setattr, scheduler, "JOB_BEAT_INTERVAL", original)

        job = scheduler.Job("slow", always_due, slow, timeout=timedelta(seconds=1))
        await scheduler.run_due_jobs([job], utc(2026, 10, 3, 12, 0), heartbeat=lambda: beats.append(1))

        self.assertGreaterEqual(len(beats), 3)  # the one before the job, then one per interval while it runs

    async def test_stops_beating_after_the_job_timeout(self):
        beats = []

        async def swallows_cancellation():
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(0.5)

        original = scheduler.JOB_BEAT_INTERVAL
        scheduler.JOB_BEAT_INTERVAL = timedelta(seconds=0.05)
        self.addCleanup(setattr, scheduler, "JOB_BEAT_INTERVAL", original)

        job = scheduler.Job("stuck", always_due, swallows_cancellation, timeout=timedelta(seconds=0.1))
        await scheduler.run_due_jobs([job], utc(2026, 10, 3, 12, 0), heartbeat=lambda: beats.append(1))

        self.assertLessEqual(len(beats), 3)  # before the job, then at most timeout / interval


class FailureAlertTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db_path = use_temporary_database(self)
        self.alerts = []
        self.fail = True

    async def alert(self, message):
        self.alerts.append(message)

    def job(self, alert_after=timedelta(days=1)):
        async def run():
            if self.fail:
                raise RuntimeError("CTFtime is down")

        return scheduler.Job("flaky", always_due, run, alert_after=alert_after)

    async def tick(self, jobs, now):
        if not self.fail:
            await scheduler.run_due_jobs(jobs, now, alert=self.alert)
            return
        with self.assertLogs("bot", level="ERROR"):
            await scheduler.run_due_jobs(jobs, now, alert=self.alert)

    async def test_alerts_once_after_failing_for_the_alert_time(self):
        jobs = [self.job()]
        start = utc(2026, 11, 1, 9, 0)

        await self.tick(jobs, start)
        await self.tick(jobs, start + timedelta(hours=23, minutes=55))
        self.assertEqual(self.alerts, [])

        await self.tick(jobs, start + timedelta(days=1))
        await self.tick(jobs, start + timedelta(days=1, minutes=5))
        await self.tick(jobs, start + timedelta(days=3))

        self.assertEqual(len(self.alerts), 1)
        self.assertIn("flaky", self.alerts[0])
        self.assertIn("CTFtime is down", self.alerts[0])

    async def test_failing_since_survives_a_restart(self):
        jobs = [self.job()]
        start = utc(2026, 11, 1, 9, 0)
        await self.tick(jobs, start)

        db.close()
        db.init(self.db_path)
        await self.tick(jobs, start + timedelta(days=1))

        self.assertEqual(len(self.alerts), 1)

    async def test_success_starts_a_new_failure_period(self):
        jobs = [self.job()]
        start = utc(2026, 11, 1, 9, 0)
        await self.tick(jobs, start)
        await self.tick(jobs, start + timedelta(days=1))

        self.fail = False
        await self.tick(jobs, start + timedelta(days=1, minutes=5))
        self.fail = True
        await self.tick(jobs, start + timedelta(days=2))
        self.assertEqual(len(self.alerts), 1)

        await self.tick(jobs, start + timedelta(days=3))
        self.assertEqual(len(self.alerts), 2)

    async def test_long_error_with_backticks_stays_one_code_span(self):
        async def run():
            raise RuntimeError("`" * 5000)

        jobs = [scheduler.Job("flaky", always_due, run, alert_after=timedelta(days=1))]
        start = utc(2026, 11, 1, 9, 0)
        await self.tick(jobs, start)
        await self.tick(jobs, start + timedelta(days=1))

        self.assertLess(len(self.alerts[0]), 2000)
        self.assertEqual(self.alerts[0].count("`"), 4)

    async def test_job_without_alert_time_never_alerts(self):
        jobs = [self.job(alert_after=None)]
        start = utc(2026, 11, 1, 9, 0)

        await self.tick(jobs, start)
        await self.tick(jobs, start + timedelta(days=7))

        self.assertEqual(self.alerts, [])

    async def test_alert_that_fails_is_tried_again_next_tick(self):
        jobs = [self.job()]
        start = utc(2026, 11, 1, 9, 0)
        attempts = []

        async def broken_then_working_alert(message):
            attempts.append(message)
            if len(attempts) == 1:
                raise RuntimeError("Discord is down too")

        with self.assertLogs("bot", level="ERROR") as logs:
            await scheduler.run_due_jobs(jobs, start, alert=broken_then_working_alert)
            await scheduler.run_due_jobs(jobs, start + timedelta(days=1), alert=broken_then_working_alert)
            await scheduler.run_due_jobs(jobs, start + timedelta(days=1, minutes=5), alert=broken_then_working_alert)
            await scheduler.run_due_jobs(jobs, start + timedelta(days=1, minutes=10), alert=broken_then_working_alert)

        self.assertEqual(len(attempts), 2)
        self.assertIn("Discord is down too", "\n".join(logs.output))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class WatchdogTest(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.exits = []
        self.watchdog = scheduler.Watchdog(timedelta(minutes=20), clock=self.clock, on_timeout=lambda: self.exits.append(1))

    def test_exits_when_heartbeat_is_too_old(self):
        self.watchdog.beat()
        self.clock.now += 19 * 60
        self.watchdog.check()
        self.assertEqual(self.exits, [])

        self.clock.now += 2 * 60
        with self.assertLogs("bot", level="CRITICAL"):
            self.watchdog.check()
        self.assertEqual(self.exits, [1])

    def test_beat_keeps_it_alive(self):
        for _ in range(10):
            self.clock.now += 5 * 60
            self.watchdog.beat()
            self.watchdog.check()

        self.assertEqual(self.exits, [])


class TickLoopTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.calls = []

    def make_loop(self, jobs):
        loop = scheduler.TickLoop(jobs, scheduler.Watchdog(timedelta(minutes=20)),
                                  interval=timedelta(hours=1), restart_delay=timedelta(0))
        self.addAsyncCleanup(loop.stop)
        return loop

    def counting_job(self, is_due=always_due):
        async def run():
            self.calls.append("tick")

        return scheduler.Job("count", is_due, run)

    async def wait_for_calls(self, count):
        async def poll():
            while len(self.calls) < count:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(poll(), timeout=5)

    async def test_starting_again_on_reconnect_keeps_one_loop(self):
        loop = self.make_loop([self.counting_job()])

        loop.start()
        await self.wait_for_calls(1)
        loop.start()
        await asyncio.sleep(0.1)

        self.assertEqual(self.calls, ["tick"])

    async def test_exception_escaping_the_tick_restarts_the_loop(self):
        raised = []

        def due_but_explodes_once(now, last_run_at):
            if not raised:
                raised.append(1)
                raise RuntimeError("escaped the tick")
            return True

        loop = self.make_loop([self.counting_job(is_due=due_but_explodes_once)])

        with self.assertLogs("bot", level="ERROR") as logs:
            loop.start()
            await self.wait_for_calls(1)

        self.assertEqual(self.calls, ["tick"])
        self.assertIn("RuntimeError: escaped the tick", "\n".join(logs.output))
