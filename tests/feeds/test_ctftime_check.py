import asyncio
import unittest

from ctf import store
from feeds import ctftime_check
from feeds.calendar.sessions import Session, linked_sessions
from feeds.ctftime import Event
from feeds.ctftime_check import Record
from tests.factories import new_ctf, use_temporary_database, utc
from tests.fakes import FakeCtftime
from tests.feeds.calendar.factories import store_session

CTF_START = utc(2026, 10, 10, 8)
CTF_FINISH = utc(2026, 10, 12, 8)


def event(start=CTF_START, finish=CTF_FINISH, title="Foo CTF"):
    return Event(
        id=3352,
        title=title,
        start=start,
        finish=finish,
        format="Jeopardy",
        weight=25.0,
        onsite=False,
        url="https://foo.example",
        ctftime_url="https://ctftime.org/event/3352/",
    )


def session(start=utc(2026, 10, 10, 17), end=utc(2026, 10, 10, 22), title="CTF night"):
    return Session(title=title, start=start, end=end)


def record(
    start=CTF_START, finish=CTF_FINISH, told_start=CTF_START, told_finish=CTF_FINISH, title="Foo CTF", gone=False
):
    return Record(
        ctftime_id=3352,
        title=title,
        start=start,
        finish=finish,
        told_start=told_start,
        told_finish=told_finish,
        gone=gone,
    )


def decide(stored, found, sessions=None):
    return ctftime_check.compare_with_ctftime(3352, stored, found, [session()] if sessions is None else sessions)


class FirstSightTest(unittest.TestCase):
    def test_first_sight_is_stored_without_an_alert(self):
        outcome = decide(None, event())

        self.assertIsNone(outcome.alert)
        self.assertEqual(outcome.record, record())

    def test_session_outside_the_ctf_on_first_sight_is_alerted_straight_away(self):
        typo = session(start=utc(2026, 11, 10, 17), end=utc(2026, 11, 10, 22), title="CTF night (typo)")

        outcome = decide(None, event(), [session(), typo])

        self.assertTrue(outcome.alert.startswith(":warning:"))
        self.assertIn("Foo CTF", outcome.alert)
        self.assertIn("CTF night (typo)", outcome.alert)
        self.assertIn(f"<t:{int(utc(2026, 11, 10, 17).timestamp())}:F>", outcome.alert)
        self.assertEqual(outcome.record, record())


NEW_START = utc(2026, 10, 9, 8)
NEW_FINISH = utc(2026, 10, 11, 8)


class ChangeTest(unittest.TestCase):
    def test_unchanged_event_posts_nothing(self):
        outcome = decide(record(), event())

        self.assertIsNone(outcome.alert)
        self.assertEqual(outcome.record, record())

    def test_changed_title_alone_posts_nothing_and_is_stored(self):
        outcome = decide(record(), event(title="Foo CTF 2026"))

        self.assertIsNone(outcome.alert)
        self.assertEqual(outcome.record, record(title="Foo CTF 2026"))

    def test_change_with_every_session_still_in_the_ctf_is_a_notice(self):
        outcome = decide(record(), event(start=NEW_START, finish=NEW_FINISH))

        self.assertTrue(outcome.alert.startswith(":information_source:"))
        for moment in (CTF_START, CTF_FINISH, NEW_START, NEW_FINISH, utc(2026, 10, 10, 17)):
            self.assertIn(f"<t:{int(moment.timestamp())}:F>", outcome.alert)
        self.assertIn("Foo CTF", outcome.alert)
        self.assertIn("CTF night", outcome.alert)
        self.assertEqual(
            outcome.record, record(start=NEW_START, finish=NEW_FINISH, told_start=NEW_START, told_finish=NEW_FINISH)
        )

    def test_change_leaving_a_session_outside_the_ctf_is_a_warning(self):
        late = session(start=utc(2026, 10, 11, 17), end=utc(2026, 10, 11, 22), title="Second night")

        outcome = decide(record(), event(start=NEW_START, finish=NEW_FINISH), [session(), late])

        self.assertTrue(outcome.alert.startswith(":warning:"))
        self.assertIn("Second night", outcome.alert)
        self.assertIn("outside the CTF", outcome.alert)

    def test_change_of_a_ctf_without_sessions_is_a_notice_without_session_lines(self):
        # A CTF that is set up is checked also when no calendar session links to it
        outcome = decide(record(), event(start=NEW_START, finish=NEW_FINISH), [])

        self.assertTrue(outcome.alert.startswith(":information_source:"))
        self.assertIn("no calendar sessions", outcome.alert)
        self.assertNotIn("every calendar session", outcome.alert)
        self.assertTrue(outcome.alert.endswith(f"<t:{int(NEW_FINISH.timestamp())}:F>"))

    def test_only_the_finish_changing_is_alerted(self):
        outcome = decide(record(), event(finish=NEW_FINISH))

        self.assertIsNotNone(outcome.alert)

    def test_change_already_alerted_posts_nothing(self):
        alerted = record(start=NEW_START, finish=NEW_FINISH, told_start=NEW_START, told_finish=NEW_FINISH)

        outcome = decide(alerted, event(start=NEW_START, finish=NEW_FINISH))

        self.assertIsNone(outcome.alert)

    def test_change_that_was_not_alerted_yet_is_alerted(self):
        # The data of the last check was stored, but its alert was not posted
        missed = record(start=NEW_START, finish=NEW_FINISH)

        outcome = decide(missed, event(start=NEW_START, finish=NEW_FINISH))

        self.assertIn(f"<t:{int(CTF_START.timestamp())}:F>", outcome.alert)

    def test_change_back_to_what_was_alerted_posts_nothing(self):
        outcome = decide(record(start=NEW_START, finish=NEW_FINISH), event())

        self.assertIsNone(outcome.alert)


class GoneTest(unittest.TestCase):
    def test_event_gone_from_ctftime_is_alerted(self):
        outcome = decide(record(), None)

        self.assertTrue(outcome.alert.startswith(":warning:"))
        self.assertIn("Foo CTF", outcome.alert)
        self.assertIn("CTF night", outcome.alert)
        self.assertEqual(outcome.record, record(gone=True))

    def test_event_of_a_ctf_without_sessions_gone_from_ctftime_does_not_point_to_sessions(self):
        outcome = decide(record(), None, [])

        self.assertTrue(outcome.alert.startswith(":warning:"))
        self.assertNotIn("calendar session", outcome.alert)
        self.assertTrue(outcome.alert.endswith("is not found)."))

    def test_event_already_alerted_as_gone_posts_nothing(self):
        outcome = decide(record(gone=True), None)

        self.assertIsNone(outcome.alert)
        self.assertEqual(outcome.record, record(gone=True))

    def test_event_never_found_on_ctftime_is_alerted(self):
        outcome = decide(None, None)

        self.assertIn("3352", outcome.alert)
        self.assertIn("CTF night", outcome.alert)
        self.assertEqual(
            outcome.record,
            Record(ctftime_id=3352, title=None, start=None, finish=None, told_start=None, told_finish=None, gone=True),
        )

    def test_event_back_on_ctftime_with_the_same_dates_posts_nothing(self):
        outcome = decide(record(gone=True), event())

        self.assertIsNone(outcome.alert)
        self.assertEqual(outcome.record, record())

    def test_event_never_found_that_shows_up_is_a_first_sight(self):
        never_found = decide(None, None).record

        outcome = decide(never_found, event())

        self.assertIsNone(outcome.alert)
        self.assertEqual(outcome.record, record())


class LengthTest(unittest.TestCase):
    def test_alert_with_many_long_sessions_fits_in_one_discord_message(self):
        sessions = [
            session(start=utc(2026, 11, day, 17), end=utc(2026, 11, day, 22), title="*_" * 200) for day in range(1, 31)
        ]

        outcome = decide(record(), event(start=NEW_START, finish=NEW_FINISH, title="~" * 300), sessions)

        self.assertLessEqual(len(outcome.alert), 2000)
        self.assertIn("more", outcome.alert)


NOW = utc(2026, 10, 3, 10)


def run_check(now, alert, get_event):
    """The check as the bot runs it: also for the CTFs set up, with their dates following CTFtime."""
    return ctftime_check.check(now, alert, store.ctftime_ids_not_locked(), store.set_dates, get_event)


class CheckTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.alerts = []
        self.alert_fails = False

    async def alert(self, ctftime_id, message):
        if self.alert_fails:
            raise RuntimeError("Discord is down")
        self.alerts.append((ctftime_id, message))

    def add_session(
        self, uid, start=utc(2026, 10, 10, 17), end=utc(2026, 10, 10, 22), url="https://ctftime.org/event/3352/"
    ):
        store_session(uid, start, end, f"Session {uid}", url)

    async def check(self, ctftime, now=NOW):
        return await run_check(now, self.alert, ctftime.get_event)

    async def test_first_check_stores_the_event_without_an_alert(self):
        self.add_session("night")

        result = await self.check(FakeCtftime({3352: event()}))

        self.assertEqual(result, ctftime_check.CtftimeCheckResult(checked=1, alerts=0))
        self.assertEqual(self.alerts, [])

    async def test_changed_dates_are_alerted_once_listing_every_session(self):
        self.add_session("night-1")
        self.add_session("night-2", start=utc(2026, 10, 11, 17), end=utc(2026, 10, 11, 22))
        await self.check(FakeCtftime({3352: event()}))
        moved = FakeCtftime({3352: event(start=NEW_START, finish=NEW_FINISH)})

        first = await self.check(moved)
        second = await self.check(moved)

        self.assertEqual((first.alerts, second.alerts), (1, 0))
        self.assertEqual(len(self.alerts), 1)
        ctftime_id, message = self.alerts[0]
        self.assertEqual(ctftime_id, 3352)
        self.assertTrue(message.startswith(":warning:"))
        self.assertIn("Session night-1", message)
        self.assertIn("Session night-2", message)

    async def test_sessions_linking_to_the_same_ctf_are_checked_once(self):
        self.add_session("night-1")
        self.add_session("night-2")
        ctftime = FakeCtftime({3352: event()})

        result = await self.check(ctftime)

        self.assertEqual((result.checked, ctftime.asked), (1, [3352]))

    async def test_only_ctfs_with_a_session_that_is_not_over_are_checked(self):
        self.add_session(
            "over", start=utc(2026, 10, 1, 17), end=utc(2026, 10, 1, 22), url="https://ctftime.org/event/1/"
        )
        self.add_session(
            "running", start=utc(2026, 10, 3, 8), end=utc(2026, 10, 3, 12), url="https://ctftime.org/event/2/"
        )
        self.add_session("meetup", url="https://example.com")
        ctftime = FakeCtftime()

        await self.check(ctftime)

        self.assertEqual(ctftime.asked, [2])

    async def test_gone_event_is_alerted_once(self):
        self.add_session("night")
        await self.check(FakeCtftime({3352: event()}))

        await self.check(FakeCtftime())
        await self.check(FakeCtftime())

        self.assertEqual(len(self.alerts), 1)
        self.assertIn("gone", self.alerts[0][1])

    async def test_ctftime_error_skips_that_event_without_an_alert(self):
        self.add_session("broken", url="https://ctftime.org/event/1/")
        self.add_session("fine", url="https://ctftime.org/event/2/")

        with self.assertLogs("bot", level="WARNING"):
            result = await self.check(FakeCtftime({2: event()}, broken={1}))

        self.assertEqual((result, self.alerts), (ctftime_check.CtftimeCheckResult(checked=1, alerts=0, skipped=1), []))

    async def test_ctftime_error_does_not_lose_what_was_stored(self):
        self.add_session("night")
        await self.check(FakeCtftime({3352: event()}))
        with self.assertLogs("bot", level="WARNING"):
            await self.check(FakeCtftime(broken={3352}))

        await self.check(FakeCtftime({3352: event(start=NEW_START, finish=NEW_FINISH)}))

        self.assertEqual(len(self.alerts), 1)

    async def test_alert_that_could_not_be_posted_is_posted_on_the_next_check(self):
        self.add_session("night")
        await self.check(FakeCtftime({3352: event()}))
        moved = FakeCtftime({3352: event(start=NEW_START, finish=NEW_FINISH)})
        self.alert_fails = True
        with self.assertLogs("bot", level="ERROR"):
            failed = await self.check(moved)
        self.alert_fails = False

        retried = await self.check(moved)

        self.assertEqual((failed.alerts, retried.alerts), (0, 1))

    async def test_check_stopped_while_alerting_is_not_alerted_again_by_the_next_check(self):
        self.add_session("night")
        await self.check(FakeCtftime({3352: event()}))
        moved = FakeCtftime({3352: event(start=NEW_START, finish=NEW_FINISH)})
        posting = asyncio.Event()
        release = asyncio.Event()

        async def slow_alert(ctftime_id, message):
            posting.set()
            await release.wait()
            self.alerts.append((ctftime_id, message))

        stopped = asyncio.create_task(run_check(NOW, slow_alert, moved.get_event))
        await posting.wait()
        stopped.cancel()
        next_check = asyncio.create_task(self.check(moved))
        await asyncio.sleep(0)
        release.set()
        await next_check

        self.assertEqual(len(self.alerts), 1)

    async def test_linked_sessions_are_grouped_per_ctf_leaving_out_normal_events(self):
        self.add_session("night-1")
        self.add_session("night-2", start=utc(2026, 10, 11, 17), end=utc(2026, 10, 11, 22))
        self.add_session("other", url="https://ctftime.org/event/1/")
        self.add_session("meetup", url="https://example.com")

        linked = linked_sessions()

        self.assertEqual(
            linked,
            {
                1: [Session("Session other", utc(2026, 10, 10, 17), utc(2026, 10, 10, 22))],
                3352: [
                    Session("Session night-1", utc(2026, 10, 10, 17), utc(2026, 10, 10, 22)),
                    Session("Session night-2", utc(2026, 10, 11, 17), utc(2026, 10, 11, 22)),
                ],
            },
        )

    async def test_session_moved_off_the_ctf_link_is_no_longer_checked(self):
        self.add_session("night")
        self.add_session("night", url="https://example.com")
        ctftime = FakeCtftime({3352: event()})

        result = await self.check(ctftime)

        self.assertEqual((result.checked, ctftime.asked), (0, []))

    def set_up_ctf(self, ctftime_id=3352, locked=False):
        ctf = store.create(new_ctf(name=f"CTF {ctftime_id}", ctftime_id=ctftime_id, start=CTF_START, finish=CTF_FINISH))
        if locked:
            store.mark_locked(ctf.id, NOW)
        return ctf

    async def test_changed_dates_are_stored_on_the_ctf_that_is_set_up(self):
        self.add_session("night")
        self.set_up_ctf()

        await self.check(FakeCtftime({3352: event(start=NEW_START, finish=NEW_FINISH)}))

        stored = store.find(ctftime_id=3352)
        self.assertEqual((stored.start, stored.finish), (NEW_START, NEW_FINISH))

    async def test_a_ctf_set_up_and_not_locked_is_checked_without_a_session_left(self):
        self.set_up_ctf(1)
        self.set_up_ctf(2, locked=True)
        ctftime = FakeCtftime({1: event()})

        result = await self.check(ctftime)

        self.assertEqual((result.checked, ctftime.asked), (1, [1]))


if __name__ == "__main__":
    unittest.main()
