import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from feeds import FeedError
from feeds.calendar.parse import EmptyFeed, Occurrence, parse_occurrences
from tests.factories import utc
from tests.feeds.calendar.factories import NOW, WEEKLY, WINDOW, brussels, event, feed, occurrence, parse, plan


class ParseOccurrencesTest(unittest.TestCase):
    def test_timed_event(self):
        occurrences = parse("""
UID:meeting-1
DTSTART;TZID=Europe/Brussels:20261010T200000
DTEND;TZID=Europe/Brussels:20261010T220000
SUMMARY:Weekly meeting
DESCRIPTION:Bring snacks\\, please
LOCATION:Room 1
URL:https://example.com
""")

        self.assertEqual(
            occurrences,
            [
                Occurrence(
                    uid="meeting-1",
                    start=utc(2026, 10, 10, 18),
                    end=utc(2026, 10, 10, 20),
                    title="Weekly meeting",
                    description="Bring snacks, please",
                    location="Room 1",
                    url="https://example.com",
                )
            ],
        )

    def test_html_description_becomes_plain_text_and_still_links_the_ctf(self):
        occurrences = parse("""
UID:meeting-1
DTSTART:20261010T180000Z
DTEND:20261010T200000Z
DESCRIPTION:On campus<br><br><a href="https://ctftime.org/event/2345">https://ctftime.org/event/2345</a>
""")

        self.assertEqual(occurrences[0].description, "On campus\n\nhttps://ctftime.org/event/2345")
        self.assertEqual(occurrences[0].ctftime_id, 2345)

    def test_utc_times_and_missing_fields(self):
        occurrences = parse("""
UID:meeting-1
DTSTART:20261010T180000Z
DTEND:20261010T200000Z
""")

        self.assertEqual(occurrences, [occurrence(title="")])

    def test_duration_instead_of_end(self):
        occurrences = parse("""
UID:meeting-1
DTSTART:20261010T180000Z
DURATION:PT2H
SUMMARY:Weekly meeting
""")

        self.assertEqual(occurrences[0].end, utc(2026, 10, 10, 20))

    def test_floating_time_is_in_the_timezone(self):
        occurrences = parse("""
UID:meeting-1
DTSTART:20261010T200000
DTEND:20261010T220000
SUMMARY:Weekly meeting
""")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (utc(2026, 10, 10, 18), utc(2026, 10, 10, 20)))

    def test_event_without_end_is_skipped(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(parse("UID:meeting-1\nDTSTART:20261010T180000Z\nSUMMARY:Weekly meeting"), [])

    def test_event_without_uid_is_skipped(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(parse("DTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSUMMARY:Weekly meeting"), [])

    def test_cancelled_event_is_skipped(self):
        occurrences = parse("UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSTATUS:CANCELLED")

        self.assertEqual(occurrences, [])

    def test_event_with_a_broken_time_is_skipped_and_others_still_parse(self):
        with self.assertLogs("bot", level="WARNING") as logs:
            occurrences = parse(
                "UID:broken-end\nDTSTART:20261010T180000Z\nDTEND:not-a-time",
                "UID:broken-duration\nDTSTART:20261010T180000Z\nDURATION:two hours",
                "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z",
            )

        self.assertEqual([occurrence.uid for occurrence in occurrences], ["meeting-1"])
        self.assertEqual(len(logs.output), 2)

    def test_finished_and_far_away_events_are_left_out(self):
        occurrences = parse(
            "UID:past\nDTSTART:20260901T180000Z\nDTEND:20260901T200000Z",
            "UID:far\nDTSTART:20270101T180000Z\nDTEND:20270101T200000Z",
            "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z",
        )

        self.assertEqual([occurrence.uid for occurrence in occurrences], ["meeting-1"])

    def test_known_event_moved_beyond_the_window_is_parsed(self):
        occurrences = parse("UID:meeting-1\nDTSTART:20270101T180000Z\nDURATION:PT2H", known=[("meeting-1", "")])

        self.assertEqual(occurrences, [occurrence(start=utc(2027, 1, 1, 18), end=utc(2027, 1, 1, 20), title="")])

    def test_known_event_gone_from_the_feed_is_not_parsed(self):
        occurrences = parse(
            "UID:meeting-2\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z", known=[("meeting-1", "")]
        )

        self.assertEqual([occurrence.uid for occurrence in occurrences], ["meeting-2"])

    def test_known_event_moved_into_the_window_is_parsed_once(self):
        occurrences = parse(
            "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z", known=[("meeting-1", "")]
        )

        self.assertEqual(occurrences, [occurrence(title="")])

    def test_running_event_is_parsed(self):
        occurrences = parse("UID:running\nDTSTART:20261002T180000Z\nDTEND:20261004T200000Z")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (utc(2026, 10, 2, 18), utc(2026, 10, 4, 20)))

    def test_feed_that_is_not_ics_raises(self):
        with self.assertRaises(FeedError):
            parse_occurrences(b"<html>Not found</html>", "Europe/Brussels", NOW, WINDOW)


class EmptyFeedTest(unittest.TestCase):
    def test_empty_feed_while_events_are_managed_raises(self):
        with self.assertRaises(EmptyFeed):
            parse(known=[("meeting-1", "")])

    def test_empty_feed_is_a_feed_error(self):
        # So the sync skips it like a failed download, changing nothing
        self.assertTrue(issubclass(EmptyFeed, FeedError))

    def test_empty_feed_without_managed_events_is_fine(self):
        self.assertEqual(parse(), [])

    def test_feed_with_only_unusable_events_while_events_are_managed_raises(self):
        with self.assertLogs("bot", level="WARNING"), self.assertRaises(EmptyFeed):
            parse("UID:meeting-1\nDTSTART:20261010T180000Z\nSUMMARY:No end", known=[("meeting-1", "")])

    def test_feed_with_events_outside_the_window_is_not_empty(self):
        later = "UID:later\nDTSTART:20270110T180000Z\nDTEND:20270110T200000Z"

        self.assertEqual(parse(later, known=[("meeting-1", "")]), [])

    def test_feed_with_only_cancelled_events_is_not_empty(self):
        cancelled = "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSTATUS:CANCELLED"

        self.assertEqual(parse(cancelled, known=[("meeting-1", "")]), [])


class RecurringTest(unittest.TestCase):
    def test_weekly_event_has_one_occurrence_per_week_in_the_window(self):
        occurrences = parse(WEEKLY)

        self.assertEqual(
            [occurrence.start for occurrence in occurrences],
            [utc(2026, 10, 10, 18), utc(2026, 10, 17, 18), utc(2026, 10, 24, 18), utc(2026, 10, 31, 18)],
        )
        self.assertTrue(all(occurrence.end - occurrence.start == timedelta(hours=2) for occurrence in occurrences))
        self.assertTrue(all(occurrence.title == "Weekly meeting" for occurrence in occurrences))
        self.assertEqual(len({occurrence.key for occurrence in occurrences}), 4)

    def test_window_rolling_forward_creates_only_the_next_occurrence(self):
        first_sync = plan(parse(WEEKLY))
        known = {action.occurrence.key: action.details for action in first_sync}
        week_later = NOW + timedelta(days=7)

        actions = plan(parse(WEEKLY, now=week_later), known=known, now=week_later)

        self.assertEqual([action.occurrence.start for action in actions], [utc(2026, 11, 7, 18)])

    def test_floating_times_of_a_series_are_in_the_timezone(self):
        # 20:00 in Brussels is 18:00 UTC in summer time and 19:00 UTC in winter time (from 25 October)
        occurrences = parse("UID:series\nDTSTART:20261017T200000\nDTEND:20261017T220000\nRRULE:FREQ=WEEKLY;COUNT=2")

        self.assertEqual(
            [occurrence.start for occurrence in occurrences], [utc(2026, 10, 17, 18), utc(2026, 10, 24, 18)]
        )

    def test_series_in_a_timezone_keeps_local_time_over_daylight_saving(self):
        occurrences = parse(
            "UID:series\nDTSTART;TZID=Europe/Brussels:20261017T200000\n"
            "DTEND;TZID=Europe/Brussels:20261017T220000\nRRULE:FREQ=WEEKLY;COUNT=3"
        )

        self.assertEqual(
            [occurrence.start for occurrence in occurrences],
            [utc(2026, 10, 17, 18), utc(2026, 10, 24, 18), utc(2026, 10, 31, 19)],
        )

    def test_excluded_date_is_left_out(self):
        occurrences = parse(WEEKLY + "\nEXDATE:20261017T180000Z")

        self.assertNotIn(utc(2026, 10, 17, 18), [occurrence.start for occurrence in occurrences])
        self.assertEqual(len(occurrences), 3)

    def test_override_uses_its_own_details(self):
        occurrences = parse(
            WEEKLY,
            "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T190000Z\n"
            "DTEND:20261017T213000Z\nSUMMARY:Special meeting\nLOCATION:Room 2",
        )

        moved = [occurrence for occurrence in occurrences if occurrence.title == "Special meeting"]
        self.assertEqual(len(occurrences), 4)
        self.assertEqual(len(moved), 1)
        self.assertEqual(
            (moved[0].start, moved[0].end, moved[0].location),
            (utc(2026, 10, 17, 19), utc(2026, 10, 17, 21, 30), "Room 2"),
        )

    def test_one_off_event_is_known_by_its_uid_alone(self):
        # So moving it in the calendar keeps it the same occurrence
        occurrences = parse("UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z")

        self.assertEqual(occurrences[0].key, ("meeting-1", ""))

    def test_occurrence_of_a_series_is_known_by_its_slot(self):
        self.assertEqual(parse(WEEKLY)[0].key, ("series", "2026-10-10T18:00:00+00:00"))

    def test_moved_override_keeps_the_key_of_its_slot_in_the_series(self):
        # So a later change to the override is the same occurrence, not a new one
        occurrences = parse(
            WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T190000Z\nDTEND:20261017T210000Z"
        )

        moved = [occurrence for occurrence in occurrences if occurrence.start == utc(2026, 10, 17, 19)]
        self.assertEqual(moved[0].key, ("series", "2026-10-17T18:00:00+00:00"))

    def test_known_override_moved_beyond_the_window_is_parsed(self):
        occurrences = parse(
            WEEKLY,
            "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261217T190000Z\n"
            "DTEND:20261217T210000Z\nSUMMARY:Moved meeting",
            known=[("series", "2026-10-17T18:00:00+00:00")],
        )

        moved = [occurrence for occurrence in occurrences if occurrence.title == "Moved meeting"]
        self.assertEqual(
            [(occurrence.start, occurrence.key) for occurrence in moved],
            [(utc(2026, 12, 17, 19), ("series", "2026-10-17T18:00:00+00:00"))],
        )

    def test_known_floating_override_moved_beyond_the_window_is_parsed_in_the_calendars_timezone(self):
        # Floating times are read in X-WR-TIMEZONE, so the slot found beyond the window is the one the window had
        ics = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-TIMEZONE:America/New_York\r\n"
            b"BEGIN:VEVENT\r\nUID:series\r\nDTSTART:20261010T180000\r\nDTEND:20261010T200000\r\nRRULE:FREQ=WEEKLY\r\n"
            b"END:VEVENT\r\nBEGIN:VEVENT\r\nUID:series\r\nRECURRENCE-ID:20261017T180000\r\n"
            b"DTSTART:20261217T180000\r\nDTEND:20261217T200000\r\nSUMMARY:Moved meeting\r\nEND:VEVENT\r\n"
            b"END:VCALENDAR\r\n"
        )
        key = ("series", "2026-10-17T22:00:00+00:00")
        in_window = parse_occurrences(ics, "Europe/Brussels", NOW, timedelta(days=90))
        self.assertIn(key, [occurrence.key for occurrence in in_window if occurrence.title == "Moved meeting"])

        occurrences = parse_occurrences(ics, "Europe/Brussels", NOW, WINDOW, {key})

        self.assertEqual(
            [occurrence.start for occurrence in occurrences if occurrence.key == key], [utc(2026, 12, 17, 23)]
        )

    def test_known_occurrence_of_a_series_beyond_the_window_is_parsed(self):
        # Created while the window was longer, so it is still in the feed and must not count as cancelled
        occurrences = parse(WEEKLY, known=[("series", "2026-11-28T18:00:00+00:00")])

        self.assertIn(
            (utc(2026, 11, 28, 18), ("series", "2026-11-28T18:00:00+00:00")),
            [(occurrence.start, occurrence.key) for occurrence in occurrences],
        )

    def test_known_occurrence_of_a_series_beyond_the_window_and_excluded_is_not_parsed(self):
        occurrences = parse(WEEKLY + "\nEXDATE:20261128T180000Z", known=[("series", "2026-11-28T18:00:00+00:00")])

        self.assertNotIn(("series", "2026-11-28T18:00:00+00:00"), [occurrence.key for occurrence in occurrences])

    def test_known_override_moved_beyond_the_window_and_cancelled_is_not_parsed(self):
        occurrences = parse(
            WEEKLY,
            "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261217T190000Z\n"
            "DTEND:20261217T210000Z\nSTATUS:CANCELLED",
            known=[("series", "2026-10-17T18:00:00+00:00")],
        )

        self.assertNotIn(("series", "2026-10-17T18:00:00+00:00"), [occurrence.key for occurrence in occurrences])

    def test_cancelled_override_is_left_out(self):
        occurrences = parse(
            WEEKLY,
            "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T180000Z\n"
            "DTEND:20261017T200000Z\nSTATUS:CANCELLED",
        )

        self.assertEqual(
            [occurrence.start for occurrence in occurrences],
            [utc(2026, 10, 10, 18), utc(2026, 10, 24, 18), utc(2026, 10, 31, 18)],
        )

    def test_cancelled_status_in_lower_case_is_left_out(self):
        self.assertEqual(parse("UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSTATUS:cancelled"), [])

    def test_date_start_with_a_timed_end_is_skipped(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(parse("UID:mixed\nDTSTART;VALUE=DATE:20261010\nDTEND:20261010T200000Z"), [])

    def test_series_without_end_is_skipped(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(parse("UID:series\nDTSTART:20261010T180000Z\nRRULE:FREQ=WEEKLY"), [])

    def test_series_with_a_broken_rule_is_skipped_and_others_still_parse(self):
        with self.assertLogs("bot", level="WARNING"):
            occurrences = parse(
                "UID:broken\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nRRULE:FREQ=SOMETIMES",
                "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z",
            )

        self.assertEqual([occurrence.uid for occurrence in occurrences], ["meeting-1"])

    def test_occurrence_known_by_its_slot_is_not_created_again(self):
        moved = occurrence(
            uid="series", start=utc(2026, 10, 17, 19), end=utc(2026, 10, 17, 21), slot=utc(2026, 10, 17, 18)
        )

        in_discord = event(start=utc(2026, 10, 17, 19), end=utc(2026, 10, 17, 21))

        self.assertEqual(plan([moved], known={("series", "2026-10-17T18:00:00+00:00"): in_discord}), [])


class AllDayTest(unittest.TestCase):
    def test_all_day_event_runs_from_midnight_to_23_59_in_the_timezone(self):
        occurrences = parse("UID:day\nDTSTART;VALUE=DATE:20261010\nDTEND;VALUE=DATE:20261011\nSUMMARY:Holiday")

        self.assertEqual(
            (occurrences[0].start, occurrences[0].end), (brussels(2026, 10, 10), brussels(2026, 10, 10, 23, 59))
        )
        self.assertEqual(occurrences[0].title, "Holiday")

    def test_all_day_event_without_end_lasts_one_day(self):
        occurrences = parse("UID:day\nDTSTART;VALUE=DATE:20261010")

        self.assertEqual(
            (occurrences[0].start, occurrences[0].end), (brussels(2026, 10, 10), brussels(2026, 10, 10, 23, 59))
        )

    def test_multi_day_event_runs_from_the_first_day_to_23_59_on_the_last_day(self):
        # The ICS end date is the day after the last day; 25 October is the switch to winter time
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261024\nDTEND;VALUE=DATE:20261027")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (utc(2026, 10, 23, 22), utc(2026, 10, 26, 22, 59)))

    def test_multi_day_event_with_a_duration(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261010\nDURATION:P2D")

        self.assertEqual(occurrences[0].end, brussels(2026, 10, 11, 23, 59))

    def test_running_multi_day_event_is_parsed(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20260928\nDTEND;VALUE=DATE:20261006")

        self.assertEqual(
            (occurrences[0].start, occurrences[0].end), (brussels(2026, 9, 28), brussels(2026, 10, 5, 23, 59))
        )

    def test_recurring_all_day_event(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261010\nRRULE:FREQ=WEEKLY;COUNT=2")

        self.assertEqual(
            [(occurrence.start, occurrence.end) for occurrence in occurrences],
            [
                (brussels(2026, 10, 10), brussels(2026, 10, 10, 23, 59)),
                (brussels(2026, 10, 17), brussels(2026, 10, 17, 23, 59)),
            ],
        )

    def test_known_all_day_override_moved_beyond_the_window_is_parsed(self):
        occurrences = parse(
            "UID:days\nDTSTART;VALUE=DATE:20261010\nRRULE:FREQ=WEEKLY;COUNT=2",
            "UID:days\nRECURRENCE-ID;VALUE=DATE:20261017\nDTSTART;VALUE=DATE:20261217",
            known=[("days", "2026-10-16T22:00:00+00:00")],
        )

        self.assertEqual(
            [occurrence.start for occurrence in occurrences], [brussels(2026, 10, 10), brussels(2026, 12, 17)]
        )

    def test_all_day_event_in_another_timezone(self):
        occurrences = parse_occurrences(feed("UID:day\nDTSTART;VALUE=DATE:20261010"), "America/New_York", NOW, WINDOW)

        self.assertEqual(occurrences[0].start, datetime(2026, 10, 10, tzinfo=ZoneInfo("America/New_York")))

    def test_running_all_day_event_is_created_starting_in_a_minute(self):
        actions = plan(parse("UID:today\nDTSTART;VALUE=DATE:20261003"))

        self.assertEqual(len(actions), 1)
        self.assertEqual(
            (actions[0].details.start, actions[0].details.end),
            (NOW + timedelta(minutes=1), brussels(2026, 10, 3, 23, 59)),
        )
        self.assertEqual(actions[0].occurrence.start, brussels(2026, 10, 3))


class CtfSessionTest(unittest.TestCase):
    def test_ctftime_link_in_the_url_makes_a_ctf_session(self):
        occurrences = parse(
            "UID:ctf\nDTSTART:20261010T180000Z\nDTEND:20261010T220000Z\nURL:https://ctftime.org/event/3352/"
        )

        self.assertEqual(occurrences[0].ctftime_id, 3352)

    def test_ctftime_link_in_the_description_makes_a_ctf_session(self):
        occurrences = parse(
            "UID:ctf\nDTSTART:20261010T180000Z\nDTEND:20261010T220000Z\nURL:https://example.com\n"
            "DESCRIPTION:We play https://ctftime.org/event/3352 tonight"
        )

        self.assertEqual(occurrences[0].ctftime_id, 3352)

    def test_link_in_the_url_wins_over_the_description(self):
        meeting = occurrence(url="https://ctftime.org/event/1", description="Last year: https://ctftime.org/event/2")

        self.assertEqual(meeting.ctftime_id, 1)

    def test_event_without_a_ctftime_link_is_a_normal_event(self):
        meeting = occurrence(url="https://example.com", description="Meetup with pizza")

        self.assertIsNone(meeting.ctftime_id)


if __name__ == "__main__":
    unittest.main()
