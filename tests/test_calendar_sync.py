import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord

from utils import calendar_sync
from utils.calendar_sync import Create, Occurrence

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
WINDOW = timedelta(days=30)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def occurrence(uid="meeting-1", start=utc(2026, 10, 10, 18), end=utc(2026, 10, 10, 20), title="Weekly meeting",
               description="", location="", url="", slot=None):
    return Occurrence(uid=uid, start=start, end=end, title=title, description=description, location=location, url=url,
                      slot=slot)


def plan(occurrences, known=(), now=NOW):
    return calendar_sync.plan(occurrences, set(known), now, WINDOW)


class PlanTest(unittest.TestCase):
    def test_occurrence_in_the_window_is_created(self):
        meeting = occurrence(location="Room 1", description="Bring snacks")

        actions = plan([meeting])

        self.assertEqual(len(actions), 1)
        self.assertIsInstance(actions[0], Create)
        self.assertEqual(actions[0].occurrence, meeting)
        details = actions[0].details
        self.assertEqual(details.name, "Weekly meeting")
        self.assertEqual(details.start, utc(2026, 10, 10, 18))
        self.assertEqual(details.end, utc(2026, 10, 10, 20))
        self.assertEqual(details.location, "Room 1")
        self.assertEqual(details.description, "Bring snacks")

    def test_occurrence_starting_after_the_window_is_skipped(self):
        later = occurrence(start=NOW + WINDOW + timedelta(minutes=1), end=NOW + WINDOW + timedelta(hours=2))

        self.assertEqual(plan([later]), [])

    def test_occurrence_starting_at_the_end_of_the_window_is_skipped(self):
        edge = occurrence(start=NOW + WINDOW, end=NOW + WINDOW + timedelta(hours=2))

        self.assertEqual(plan([edge]), [])

    def test_finished_occurrence_is_skipped(self):
        past = occurrence(start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=1))

        self.assertEqual(plan([past]), [])

    def test_running_occurrence_is_created_starting_in_a_minute(self):
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))

        actions = plan([running])

        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0].details.start, NOW + timedelta(minutes=1))
        self.assertEqual(actions[0].details.end, NOW + timedelta(hours=1))
        self.assertEqual(actions[0].occurrence.start, NOW - timedelta(hours=1))

    def test_occurrence_starting_within_a_minute_is_moved_to_a_minute_from_now(self):
        soon = occurrence(start=NOW + timedelta(seconds=10), end=NOW + timedelta(hours=1))

        self.assertEqual(plan([soon])[0].details.start, NOW + timedelta(minutes=1))

    def test_occurrence_already_created_is_not_created_again(self):
        meeting = occurrence()

        self.assertEqual(plan([meeting], known=[("meeting-1", "2026-10-10T18:00:00+00:00")]), [])

    def test_same_start_in_another_timezone_is_the_same_occurrence(self):
        meeting = occurrence(start=datetime(2026, 10, 10, 20, tzinfo=ZoneInfo("Europe/Brussels")))

        self.assertEqual(plan([meeting], known=[("meeting-1", "2026-10-10T18:00:00+00:00")]), [])

    def test_other_occurrence_of_a_known_uid_is_created(self):
        next_week = occurrence(start=utc(2026, 10, 17, 18), end=utc(2026, 10, 17, 20))

        actions = plan([next_week], known=[("meeting-1", "2026-10-10T18:00:00+00:00")])

        self.assertEqual([action.occurrence for action in actions], [next_week])

    def test_occurrence_listed_twice_in_the_feed_is_created_once(self):
        self.assertEqual(len(plan([occurrence(), occurrence()])), 1)

    def test_occurrence_ending_at_its_start_is_skipped(self):
        # Discord refuses an event that does not end after its start
        instant = occurrence(start=utc(2026, 10, 10, 18), end=utc(2026, 10, 10, 18))

        self.assertEqual(plan([instant]), [])

    def test_running_occurrence_ending_within_a_minute_is_skipped(self):
        # Discord needs the end after the start, which can't be after moving the start to now + 1 minute
        ending = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(seconds=30))

        self.assertEqual(plan([ending]), [])


def details(meeting):
    return plan([meeting])[0].details


class LocationTest(unittest.TestCase):
    def test_location_is_used(self):
        self.assertEqual(details(occurrence(location="Room 1", url="https://example.com")).location, "Room 1")

    def test_falls_back_to_the_url(self):
        self.assertEqual(details(occurrence(url="https://example.com")).location, "https://example.com")

    def test_falls_back_to_see_description(self):
        self.assertEqual(details(occurrence()).location, "See description")

    def test_blank_location_counts_as_missing(self):
        self.assertEqual(details(occurrence(location="  \n", url="https://example.com")).location, "https://example.com")

    def test_long_location_is_cut_to_discords_limit(self):
        location = details(occurrence(location="x" * 150)).location

        self.assertEqual(location, "x" * 99 + "…")

    def test_url_too_long_for_the_location_falls_back_to_see_description(self):
        # A cut URL would be a broken link; the description has it in full
        url = "https://example.com/" + "x" * 100

        self.assertEqual(details(occurrence(url=url)).location, "See description")


class DescriptionTest(unittest.TestCase):
    def test_url_is_added_after_the_description(self):
        meeting = occurrence(description="Bring snacks", url="https://example.com")

        self.assertEqual(details(meeting).description, "Bring snacks\n\nhttps://example.com")

    def test_url_alone_without_description(self):
        self.assertEqual(details(occurrence(url="https://example.com")).description, "https://example.com")

    def test_description_at_the_limit_is_kept_whole(self):
        self.assertEqual(details(occurrence(description="x" * 1000)).description, "x" * 1000)

    def test_long_description_is_cut_with_ellipsis_and_url_left_out(self):
        description = details(occurrence(description="x" * 1500, url="https://example.com")).description

        self.assertEqual(description, "x" * 999 + "…")

    def test_url_that_does_not_fit_after_the_description_is_left_out(self):
        description = details(occurrence(description="x" * 990, url="https://example.com")).description

        self.assertEqual(description, "x" * 990)

    def test_url_already_in_the_description_is_not_repeated(self):
        meeting = occurrence(description="Join at https://example.com", url="https://example.com")

        self.assertEqual(details(meeting).description, "Join at https://example.com")

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(details(occurrence(description="\n Bring snacks \n")).description, "Bring snacks")


class NameTest(unittest.TestCase):
    def test_long_title_is_cut_to_discords_limit(self):
        self.assertEqual(details(occurrence(title="x" * 150)).name, "x" * 99 + "…")

    def test_missing_title_gets_a_placeholder(self):
        self.assertEqual(details(occurrence(title=" ")).name, "Untitled event")


EVENT_URL = "https://discord.com/events/1/2"


def fields(embed):
    return {field.name: field.value for field in embed.fields}


class AnnouncementTest(unittest.TestCase):
    def announce(self, meeting=None, ping_role=None):
        action = plan([meeting or occurrence(location="Room 1", description="Bring snacks")])[0]
        return calendar_sync.announcement(action, EVENT_URL, ping_role)

    def test_embed_shows_the_event(self):
        content, embed, _ = self.announce()

        self.assertEqual(embed.title, "Weekly meeting")
        self.assertEqual(embed.url, EVENT_URL)
        self.assertEqual(embed.description, "Bring snacks")
        self.assertEqual(fields(embed), {
            "Start": "<t:1791655200:F> (<t:1791655200:R>)",
            "End": "<t:1791662400:F> (<t:1791662400:R>)",
            "Location": "Room 1",
            "Event": f"[Open in Discord]({EVENT_URL})",
        })

    def test_running_event_shows_its_real_start(self):
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))

        _, embed, _ = self.announce(running)

        start = int((NOW - timedelta(hours=1)).timestamp())
        self.assertEqual(fields(embed)["Start"], f"<t:{start}:F> (<t:{start}:R>)")

    def test_long_description_is_an_excerpt(self):
        _, embed, _ = self.announce(occurrence(description="x" * 2000))

        self.assertEqual(embed.description, "x" * (calendar_sync.EXCERPT_LIMIT - 1) + "…")

    def test_pings_nobody_without_a_role(self):
        content, _, allowed_mentions = self.announce()

        self.assertIsNone(content)
        self.assertFalse(allowed_mentions.everyone)
        self.assertFalse(allowed_mentions.users)
        self.assertFalse(allowed_mentions.roles)

    def test_pings_only_the_role(self):
        role = discord.Object(id=42)

        content, _, allowed_mentions = self.announce(ping_role=role)

        self.assertEqual(content, "<@&42>")
        self.assertFalse(allowed_mentions.everyone)
        self.assertFalse(allowed_mentions.users)
        self.assertEqual(allowed_mentions.roles, [role])

    def test_mentions_in_the_calendar_text_ping_nobody(self):
        # Everything from the calendar sits in the embed, and allowed_mentions only lets the role through
        _, embed, allowed_mentions = self.announce(occurrence(title="@everyone party", description="<@&7>"))

        self.assertEqual(embed.title, "@everyone party")
        self.assertFalse(allowed_mentions.everyone)


def feed(*events):
    """An ICS calendar with these VEVENT bodies."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN"]
    for body in events:
        lines += ["BEGIN:VEVENT", *body.strip().splitlines(), "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return ("\r\n".join(lines) + "\r\n").encode()


def parse(*events, now=NOW):
    return calendar_sync.parse_occurrences(feed(*events), "Europe/Brussels", now, WINDOW)


def brussels(*args):
    return datetime(*args, tzinfo=ZoneInfo("Europe/Brussels"))


WEEKLY = "UID:series\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSUMMARY:Weekly meeting\nRRULE:FREQ=WEEKLY"


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

        self.assertEqual(occurrences, [Occurrence(
            uid="meeting-1",
            start=utc(2026, 10, 10, 18),
            end=utc(2026, 10, 10, 20),
            title="Weekly meeting",
            description="Bring snacks, please",
            location="Room 1",
            url="https://example.com",
        )])

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

    def test_running_event_is_parsed(self):
        occurrences = parse("UID:running\nDTSTART:20261002T180000Z\nDTEND:20261004T200000Z")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (utc(2026, 10, 2, 18), utc(2026, 10, 4, 20)))

    def test_feed_that_is_not_ics_raises(self):
        with self.assertRaises(calendar_sync.FeedError):
            calendar_sync.parse_occurrences(b"<html>Not found</html>", "Europe/Brussels", NOW, WINDOW)


class RecurringTest(unittest.TestCase):
    def test_weekly_event_has_one_occurrence_per_week_in_the_window(self):
        occurrences = parse(WEEKLY)

        self.assertEqual([occurrence.start for occurrence in occurrences],
                         [utc(2026, 10, 10, 18), utc(2026, 10, 17, 18), utc(2026, 10, 24, 18), utc(2026, 10, 31, 18)])
        self.assertTrue(all(occurrence.end - occurrence.start == timedelta(hours=2) for occurrence in occurrences))
        self.assertTrue(all(occurrence.title == "Weekly meeting" for occurrence in occurrences))
        self.assertEqual(len({occurrence.key for occurrence in occurrences}), 4)

    def test_window_rolling_forward_creates_only_the_next_occurrence(self):
        first_sync = plan(parse(WEEKLY))
        known = {action.occurrence.key for action in first_sync}
        week_later = NOW + timedelta(days=7)

        actions = plan(parse(WEEKLY, now=week_later), known=known, now=week_later)

        self.assertEqual([action.occurrence.start for action in actions], [utc(2026, 11, 7, 18)])

    def test_floating_times_of_a_series_are_in_the_timezone(self):
        # 20:00 in Brussels is 18:00 UTC in summer time and 19:00 UTC in winter time (from 25 October)
        occurrences = parse("UID:series\nDTSTART:20261017T200000\nDTEND:20261017T220000\nRRULE:FREQ=WEEKLY;COUNT=2")

        self.assertEqual([occurrence.start for occurrence in occurrences], [utc(2026, 10, 17, 18), utc(2026, 10, 24, 18)])

    def test_series_in_a_timezone_keeps_local_time_over_daylight_saving(self):
        occurrences = parse("UID:series\nDTSTART;TZID=Europe/Brussels:20261017T200000\n"
                            "DTEND;TZID=Europe/Brussels:20261017T220000\nRRULE:FREQ=WEEKLY;COUNT=3")

        self.assertEqual([occurrence.start for occurrence in occurrences],
                         [utc(2026, 10, 17, 18), utc(2026, 10, 24, 18), utc(2026, 10, 31, 19)])

    def test_excluded_date_is_left_out(self):
        occurrences = parse(WEEKLY + "\nEXDATE:20261017T180000Z")

        self.assertNotIn(utc(2026, 10, 17, 18), [occurrence.start for occurrence in occurrences])
        self.assertEqual(len(occurrences), 3)

    def test_override_uses_its_own_details(self):
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T190000Z\n"
                                    "DTEND:20261017T213000Z\nSUMMARY:Special meeting\nLOCATION:Room 2")

        moved = [occurrence for occurrence in occurrences if occurrence.title == "Special meeting"]
        self.assertEqual(len(occurrences), 4)
        self.assertEqual(len(moved), 1)
        self.assertEqual((moved[0].start, moved[0].end, moved[0].location),
                         (utc(2026, 10, 17, 19), utc(2026, 10, 17, 21, 30), "Room 2"))

    def test_moved_override_keeps_the_key_of_its_slot_in_the_series(self):
        # So a later change to the override is the same occurrence, not a new one
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T190000Z\n"
                                    "DTEND:20261017T210000Z")

        moved = [occurrence for occurrence in occurrences if occurrence.start == utc(2026, 10, 17, 19)]
        self.assertEqual(moved[0].key, ("series", "2026-10-17T18:00:00+00:00"))

    def test_cancelled_override_is_left_out(self):
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T180000Z\n"
                                    "DTEND:20261017T200000Z\nSTATUS:CANCELLED")

        self.assertEqual([occurrence.start for occurrence in occurrences],
                         [utc(2026, 10, 10, 18), utc(2026, 10, 24, 18), utc(2026, 10, 31, 18)])

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
        moved = occurrence(uid="series", start=utc(2026, 10, 17, 19), end=utc(2026, 10, 17, 21), slot=utc(2026, 10, 17, 18))

        self.assertEqual(plan([moved], known=[("series", "2026-10-17T18:00:00+00:00")]), [])


class AllDayTest(unittest.TestCase):
    def test_all_day_event_runs_from_midnight_to_23_59_in_the_timezone(self):
        occurrences = parse("UID:day\nDTSTART;VALUE=DATE:20261010\nDTEND;VALUE=DATE:20261011\nSUMMARY:Holiday")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (brussels(2026, 10, 10), brussels(2026, 10, 10, 23, 59)))
        self.assertEqual(occurrences[0].title, "Holiday")

    def test_all_day_event_without_end_lasts_one_day(self):
        occurrences = parse("UID:day\nDTSTART;VALUE=DATE:20261010")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (brussels(2026, 10, 10), brussels(2026, 10, 10, 23, 59)))

    def test_multi_day_event_runs_from_the_first_day_to_23_59_on_the_last_day(self):
        # The ICS end date is the day after the last day; 25 October is the switch to winter time
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261024\nDTEND;VALUE=DATE:20261027")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (utc(2026, 10, 23, 22), utc(2026, 10, 26, 22, 59)))

    def test_multi_day_event_with_a_duration(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261010\nDURATION:P2D")

        self.assertEqual(occurrences[0].end, brussels(2026, 10, 11, 23, 59))

    def test_running_multi_day_event_is_parsed(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20260928\nDTEND;VALUE=DATE:20261006")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (brussels(2026, 9, 28), brussels(2026, 10, 5, 23, 59)))

    def test_recurring_all_day_event(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261010\nRRULE:FREQ=WEEKLY;COUNT=2")

        self.assertEqual([(occurrence.start, occurrence.end) for occurrence in occurrences],
                         [(brussels(2026, 10, 10), brussels(2026, 10, 10, 23, 59)),
                          (brussels(2026, 10, 17), brussels(2026, 10, 17, 23, 59))])

    def test_all_day_event_in_another_timezone(self):
        occurrences = calendar_sync.parse_occurrences(feed("UID:day\nDTSTART;VALUE=DATE:20261010"), "America/New_York", NOW, WINDOW)

        self.assertEqual(occurrences[0].start, datetime(2026, 10, 10, tzinfo=ZoneInfo("America/New_York")))

    def test_running_all_day_event_is_created_starting_in_a_minute(self):
        actions = plan(parse("UID:today\nDTSTART;VALUE=DATE:20261003"))

        self.assertEqual(len(actions), 1)
        self.assertEqual((actions[0].details.start, actions[0].details.end), (NOW + timedelta(minutes=1), brussels(2026, 10, 3, 23, 59)))
        self.assertEqual(actions[0].occurrence.start, brussels(2026, 10, 3))


if __name__ == "__main__":
    unittest.main()
