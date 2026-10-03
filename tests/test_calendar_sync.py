import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import discord

from utils import calendar_sync
from utils.calendar_sync import Cancel, Create, EventDetails, Occurrence, Prune, Recreate, Update

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
WINDOW = timedelta(days=30)
FUTURE = NOW + timedelta(days=7)


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def occurrence(uid="meeting-1", start=utc(2026, 10, 10, 18), end=utc(2026, 10, 10, 20), title="Weekly meeting",
               description="", location="", url="", slot=None):
    return Occurrence(uid=uid, start=start, end=end, title=title, description=description, location=location, url=url,
                      slot=slot)


def event(name="Weekly meeting", description="", location="See description", start=utc(2026, 10, 10, 18),
          end=utc(2026, 10, 10, 20)):
    """The Discord event the bot has for an occurrence."""
    return EventDetails(name=name, description=description, location=location, start=start, end=end)


def plan(occurrences, known=None, now=NOW, ends=None):
    """ends defaults to every known occurrence ending in the future: it only matters for the ones gone from the feed."""
    known = known or {}
    if ends is None:
        ends = {key: FUTURE for key in known}
    return calendar_sync.plan(occurrences, known, ends, now, WINDOW)


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

        self.assertEqual(plan([meeting], known={("meeting-1", ""): event()}), [])

    def test_same_slot_in_another_timezone_is_the_same_occurrence(self):
        slot = datetime(2026, 10, 10, 20, tzinfo=ZoneInfo("Europe/Brussels"))
        meeting = occurrence(uid="series", start=slot, slot=slot)

        self.assertEqual(plan([meeting], known={("series", "2026-10-10T18:00:00+00:00"): event()}), [])

    def test_other_occurrence_of_a_known_series_is_created(self):
        next_week = occurrence(uid="series", start=utc(2026, 10, 17, 18), end=utc(2026, 10, 17, 20),
                               slot=utc(2026, 10, 17, 18))

        this_week = occurrence(uid="series", slot=utc(2026, 10, 10, 18))

        actions = plan([this_week, next_week], known={("series", "2026-10-10T18:00:00+00:00"): event()})

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


class MirrorTest(unittest.TestCase):
    def test_changed_title_updates_the_event(self):
        renamed = occurrence(title="Monthly meeting")

        actions = plan([renamed], known={("meeting-1", ""): event()})

        self.assertEqual(actions, [Update(renamed, event(name="Monthly meeting"))])

    def test_changed_time_description_and_location_update_the_event(self):
        changed = occurrence(start=utc(2026, 10, 10, 19), end=utc(2026, 10, 10, 21), description="Bring snacks",
                             location="Room 2")

        actions = plan([changed], known={("meeting-1", ""): event()})

        self.assertEqual(actions, [Update(changed, event(start=utc(2026, 10, 10, 19), end=utc(2026, 10, 10, 21),
                                                         description="Bring snacks", location="Room 2"))])

    def test_event_edited_in_discord_is_set_back_to_the_calendar(self):
        meeting = occurrence()

        actions = plan([meeting], known={("meeting-1", ""): event(name="Edited by hand", location="Somewhere")})

        self.assertEqual(actions, [Update(meeting, event())])

    def test_unchanged_occurrence_needs_no_action(self):
        self.assertEqual(plan([occurrence()], known={("meeting-1", ""): event()}), [])

    def test_known_occurrence_moved_beyond_the_window_is_updated(self):
        later = occurrence(start=NOW + WINDOW + timedelta(days=5), end=NOW + WINDOW + timedelta(days=5, hours=2))

        actions = plan([later], known={("meeting-1", ""): event()})

        self.assertEqual(actions, [Update(later, event(start=later.start, end=later.end))])

    def test_event_deleted_in_discord_is_recreated(self):
        meeting = occurrence()

        self.assertEqual(plan([meeting], known={("meeting-1", ""): None}), [Recreate(meeting, event())])

    def test_event_deleted_in_discord_beyond_the_window_is_recreated(self):
        later = occurrence(start=NOW + WINDOW + timedelta(days=5), end=NOW + WINDOW + timedelta(days=5, hours=2))

        actions = plan([later], known={("meeting-1", ""): None})

        self.assertEqual(actions, [Recreate(later, event(start=later.start, end=later.end))])

    def test_running_event_deleted_in_discord_is_recreated_starting_in_a_minute(self):
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))

        actions = plan([running], known={("meeting-1", ""): None})

        self.assertEqual(actions, [Recreate(running, event(start=NOW + timedelta(minutes=1), end=NOW + timedelta(hours=1)))])

    def test_running_event_that_started_in_discord_needs_no_action(self):
        # It was created starting a minute after the sync that saw it running, which is past by now
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))
        in_discord = event(start=NOW - timedelta(minutes=10), end=NOW + timedelta(hours=1))

        self.assertEqual(plan([running], known={("meeting-1", ""): in_discord}), [])

    def test_running_event_still_starting_in_a_minute_needs_no_action(self):
        # Created by the sync a few seconds ago, at that sync's now + 1 minute
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))
        in_discord = event(start=NOW + timedelta(seconds=40), end=NOW + timedelta(hours=1))

        self.assertEqual(plan([running], known={("meeting-1", ""): in_discord}), [])

    def test_event_moved_into_the_past_in_the_calendar_starts_in_a_minute(self):
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))

        actions = plan([running], known={("meeting-1", ""): event(end=NOW + timedelta(hours=1))})

        self.assertEqual(actions, [Update(running, event(start=NOW + timedelta(minutes=1), end=NOW + timedelta(hours=1)))])


class CancelTest(unittest.TestCase):
    def test_occurrence_removed_from_the_feed_is_cancelled(self):
        self.assertEqual(plan([], known={("meeting-1", ""): event()}), [Cancel(("meeting-1", ""))])

    def test_removed_occurrence_deleted_in_discord_is_cancelled(self):
        # The announcement still gets its cancellation reply
        self.assertEqual(plan([], known={("meeting-1", ""): None}), [Cancel(("meeting-1", ""))])

    def test_cancelled_event_is_cancelled(self):
        known = [("meeting-1", "")]
        occurrences = parse("UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSTATUS:CANCELLED", known=known)

        self.assertEqual(plan(occurrences, known={known[0]: event()}), [Cancel(known[0])])

    def test_cancelled_occurrence_of_a_series_is_cancelled(self):
        slot = ("series", "2026-10-17T18:00:00+00:00")
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T180000Z\n"
                                    "DTEND:20261017T200000Z\nSTATUS:CANCELLED", known=[slot])

        actions = plan(occurrences, known={slot: event(start=utc(2026, 10, 17, 18), end=utc(2026, 10, 17, 20))})

        # The other occurrences of the series are new
        self.assertEqual([action for action in actions if not isinstance(action, Create)], [Cancel(slot)])

    def test_occurrence_moved_outside_the_window_is_not_cancelled(self):
        later = occurrence(start=NOW + WINDOW + timedelta(days=5), end=NOW + WINDOW + timedelta(days=5, hours=2))

        actions = plan([later], known={("meeting-1", ""): event()})

        self.assertEqual([type(action) for action in actions], [Update])

    def test_other_occurrences_are_not_cancelled(self):
        self.assertEqual(plan([occurrence()], known={("meeting-1", ""): event(), ("meeting-2", ""): event()}),
                         [Cancel(("meeting-2", ""))])

    def test_finished_occurrence_in_the_feed_is_pruned(self):
        past = occurrence(start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=1))

        self.assertEqual(plan([past], known={("meeting-1", ""): None}), [Prune(("meeting-1", ""))])

    def test_occurrence_ending_now_is_pruned(self):
        ended = occurrence(start=NOW - timedelta(hours=2), end=NOW)

        self.assertEqual(plan([ended], known={("meeting-1", ""): event()}), [Prune(("meeting-1", ""))])

    def test_finished_occurrence_gone_from_the_feed_is_pruned_not_cancelled(self):
        # An occurrence of a series is no longer expanded once it is over
        slot = ("series", "2026-09-26T18:00:00+00:00")

        actions = plan([], known={slot: None}, ends={slot: utc(2026, 9, 26, 20)})

        self.assertEqual(actions, [Prune(slot)])

    def test_running_occurrence_gone_from_the_feed_is_cancelled(self):
        actions = plan([], known={("meeting-1", ""): event()}, ends={("meeting-1", ""): NOW + timedelta(hours=1)})

        self.assertEqual(actions, [Cancel(("meeting-1", ""))])

    def test_new_occurrence_that_finished_is_not_pruned(self):
        # Only what the bot created an event for is in the database
        past = occurrence(start=NOW - timedelta(hours=3), end=NOW - timedelta(hours=1))

        self.assertEqual(plan([past]), [])


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


def parse(*events, now=NOW, known=()):
    return calendar_sync.parse_occurrences(feed(*events), "Europe/Brussels", now, WINDOW, set(known))


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

    def test_known_event_moved_beyond_the_window_is_parsed(self):
        occurrences = parse("UID:meeting-1\nDTSTART:20270101T180000Z\nDURATION:PT2H", known=[("meeting-1", "")])

        self.assertEqual(occurrences, [occurrence(start=utc(2027, 1, 1, 18), end=utc(2027, 1, 1, 20), title="")])

    def test_known_event_gone_from_the_feed_is_not_parsed(self):
        occurrences = parse("UID:meeting-2\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z", known=[("meeting-1", "")])

        self.assertEqual([occurrence.uid for occurrence in occurrences], ["meeting-2"])

    def test_known_event_moved_into_the_window_is_parsed_once(self):
        occurrences = parse("UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z", known=[("meeting-1", "")])

        self.assertEqual(occurrences, [occurrence(title="")])

    def test_running_event_is_parsed(self):
        occurrences = parse("UID:running\nDTSTART:20261002T180000Z\nDTEND:20261004T200000Z")

        self.assertEqual((occurrences[0].start, occurrences[0].end), (utc(2026, 10, 2, 18), utc(2026, 10, 4, 20)))

    def test_feed_that_is_not_ics_raises(self):
        with self.assertRaises(calendar_sync.FeedError):
            calendar_sync.parse_occurrences(b"<html>Not found</html>", "Europe/Brussels", NOW, WINDOW)


class EmptyFeedTest(unittest.TestCase):
    def test_empty_feed_while_events_are_managed_raises(self):
        with self.assertRaises(calendar_sync.EmptyFeed):
            parse(known=[("meeting-1", "")])

    def test_empty_feed_is_a_feed_error(self):
        # So the sync skips it like a failed download, changing nothing
        self.assertTrue(issubclass(calendar_sync.EmptyFeed, calendar_sync.FeedError))

    def test_empty_feed_without_managed_events_is_fine(self):
        self.assertEqual(parse(), [])

    def test_feed_with_only_unusable_events_while_events_are_managed_raises(self):
        with self.assertLogs("bot", level="WARNING"), self.assertRaises(calendar_sync.EmptyFeed):
            parse("UID:meeting-1\nDTSTART:20261010T180000Z\nSUMMARY:No end", known=[("meeting-1", "")])

    def test_feed_with_events_outside_the_window_is_not_empty(self):
        later = "UID:later\nDTSTART:20270110T180000Z\nDTEND:20270110T200000Z"

        self.assertEqual(parse(later, known=[("meeting-1", "")]), [])

    def test_feed_with_only_cancelled_events_is_not_empty(self):
        cancelled = "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSTATUS:CANCELLED"

        self.assertEqual(parse(cancelled, known=[("meeting-1", "")]), [])


class FeedHealthTest(unittest.TestCase):
    def fail_times(self, health, times):
        """Whether each of times failures asks for the alert."""
        return [health.failed() for _ in range(times)]

    def test_alert_is_due_on_the_tenth_consecutive_failure(self):
        health = calendar_sync.FeedHealth(alert_after=10)

        self.assertEqual(self.fail_times(health, 10), [False] * 9 + [True])

    def test_alert_is_not_due_again_once_posted(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 10)
        health.alert_posted()

        self.assertEqual(self.fail_times(health, 5), [False] * 5)

    def test_alert_that_could_not_be_posted_is_due_on_the_next_failure(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 10)

        self.assertTrue(health.failed())

    def test_success_resets_the_count(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 9)
        health.succeeded()

        self.assertEqual(self.fail_times(health, 10), [False] * 9 + [True])

    def test_recovery_is_due_on_the_first_success_after_an_alert(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 10)
        health.alert_posted()

        self.assertEqual([health.succeeded(), health.succeeded()], [True, False])

    def test_no_recovery_without_an_alert(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 9)

        self.assertFalse(health.succeeded())

    def test_no_recovery_when_the_alert_could_not_be_posted(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 10)

        self.assertFalse(health.succeeded())

    def test_new_failures_after_recovery_alert_again(self):
        health = calendar_sync.FeedHealth(alert_after=10)
        self.fail_times(health, 10)
        health.alert_posted()
        health.succeeded()

        self.assertEqual(self.fail_times(health, 10), [False] * 9 + [True])


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
        known = {action.occurrence.key: action.details for action in first_sync}
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

    def test_one_off_event_is_known_by_its_uid_alone(self):
        # So moving it in the calendar keeps it the same occurrence
        occurrences = parse("UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z")

        self.assertEqual(occurrences[0].key, ("meeting-1", ""))

    def test_occurrence_of_a_series_is_known_by_its_slot(self):
        self.assertEqual(parse(WEEKLY)[0].key, ("series", "2026-10-10T18:00:00+00:00"))

    def test_moved_override_keeps_the_key_of_its_slot_in_the_series(self):
        # So a later change to the override is the same occurrence, not a new one
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T190000Z\n"
                                    "DTEND:20261017T210000Z")

        moved = [occurrence for occurrence in occurrences if occurrence.start == utc(2026, 10, 17, 19)]
        self.assertEqual(moved[0].key, ("series", "2026-10-17T18:00:00+00:00"))

    def test_known_override_moved_beyond_the_window_is_parsed(self):
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261217T190000Z\n"
                                    "DTEND:20261217T210000Z\nSUMMARY:Moved meeting",
                            known=[("series", "2026-10-17T18:00:00+00:00")])

        moved = [occurrence for occurrence in occurrences if occurrence.title == "Moved meeting"]
        self.assertEqual([(occurrence.start, occurrence.key) for occurrence in moved],
                         [(utc(2026, 12, 17, 19), ("series", "2026-10-17T18:00:00+00:00"))])

    def test_known_occurrence_of_a_series_beyond_the_window_is_parsed(self):
        # Created while the window was longer, so it is still in the feed and must not count as cancelled
        occurrences = parse(WEEKLY, known=[("series", "2026-11-28T18:00:00+00:00")])

        self.assertIn((utc(2026, 11, 28, 18), ("series", "2026-11-28T18:00:00+00:00")),
                      [(occurrence.start, occurrence.key) for occurrence in occurrences])

    def test_known_occurrence_of_a_series_beyond_the_window_and_excluded_is_not_parsed(self):
        occurrences = parse(WEEKLY + "\nEXDATE:20261128T180000Z", known=[("series", "2026-11-28T18:00:00+00:00")])

        self.assertNotIn(("series", "2026-11-28T18:00:00+00:00"), [occurrence.key for occurrence in occurrences])

    def test_known_override_moved_beyond_the_window_and_cancelled_is_not_parsed(self):
        occurrences = parse(WEEKLY, "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261217T190000Z\n"
                                    "DTEND:20261217T210000Z\nSTATUS:CANCELLED",
                            known=[("series", "2026-10-17T18:00:00+00:00")])

        self.assertNotIn(("series", "2026-10-17T18:00:00+00:00"), [occurrence.key for occurrence in occurrences])

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

        in_discord = event(start=utc(2026, 10, 17, 19), end=utc(2026, 10, 17, 21))

        self.assertEqual(plan([moved], known={("series", "2026-10-17T18:00:00+00:00"): in_discord}), [])


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

    def test_known_all_day_override_moved_beyond_the_window_is_parsed(self):
        occurrences = parse("UID:days\nDTSTART;VALUE=DATE:20261010\nRRULE:FREQ=WEEKLY;COUNT=2",
                            "UID:days\nRECURRENCE-ID;VALUE=DATE:20261017\nDTSTART;VALUE=DATE:20261217",
                            known=[("days", "2026-10-16T22:00:00+00:00")])

        self.assertEqual([occurrence.start for occurrence in occurrences], [brussels(2026, 10, 10), brussels(2026, 12, 17)])

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
