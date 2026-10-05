import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from feeds.calendar.plan import Cancel, Create, Prune, Recreate, Update
from tests.factories import utc
from tests.feeds.calendar.factories import NOW, WEEKLY, WINDOW, event, occurrence, parse, plan


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
        next_week = occurrence(
            uid="series", start=utc(2026, 10, 17, 18), end=utc(2026, 10, 17, 20), slot=utc(2026, 10, 17, 18)
        )

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
        changed = occurrence(
            start=utc(2026, 10, 10, 19), end=utc(2026, 10, 10, 21), description="Bring snacks", location="Room 2"
        )

        actions = plan([changed], known={("meeting-1", ""): event()})

        self.assertEqual(
            actions,
            [
                Update(
                    changed,
                    event(
                        start=utc(2026, 10, 10, 19),
                        end=utc(2026, 10, 10, 21),
                        description="Bring snacks",
                        location="Room 2",
                    ),
                )
            ],
        )

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

        self.assertEqual(
            actions, [Recreate(running, event(start=NOW + timedelta(minutes=1), end=NOW + timedelta(hours=1)))]
        )

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

    def test_running_event_moved_to_later_in_the_calendar_is_recreated(self):
        # Discord won't move the start of a running event, so it makes way for one at the new start
        later = occurrence(start=NOW + timedelta(hours=3), end=NOW + timedelta(hours=5))
        in_discord = event(start=NOW - timedelta(minutes=10), end=NOW + timedelta(hours=1))

        actions = plan([later], known={("meeting-1", ""): in_discord})

        self.assertEqual(actions, [Recreate(later, event(start=later.start, end=later.end))])

    def test_event_moved_into_the_past_in_the_calendar_starts_in_a_minute(self):
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))

        actions = plan([running], known={("meeting-1", ""): event(end=NOW + timedelta(hours=1))})

        self.assertEqual(
            actions, [Update(running, event(start=NOW + timedelta(minutes=1), end=NOW + timedelta(hours=1)))]
        )


class CancelTest(unittest.TestCase):
    def test_occurrence_removed_from_the_feed_is_cancelled(self):
        self.assertEqual(plan([], known={("meeting-1", ""): event()}), [Cancel(("meeting-1", ""))])

    def test_removed_occurrence_deleted_in_discord_is_cancelled(self):
        # The announcement still gets its cancellation reply
        self.assertEqual(plan([], known={("meeting-1", ""): None}), [Cancel(("meeting-1", ""))])

    def test_cancelled_event_is_cancelled(self):
        known = [("meeting-1", "")]
        occurrences = parse(
            "UID:meeting-1\nDTSTART:20261010T180000Z\nDTEND:20261010T200000Z\nSTATUS:CANCELLED", known=known
        )

        self.assertEqual(plan(occurrences, known={known[0]: event()}), [Cancel(known[0])])

    def test_cancelled_occurrence_of_a_series_is_cancelled(self):
        slot = ("series", "2026-10-17T18:00:00+00:00")
        occurrences = parse(
            WEEKLY,
            "UID:series\nRECURRENCE-ID:20261017T180000Z\nDTSTART:20261017T180000Z\n"
            "DTEND:20261017T200000Z\nSTATUS:CANCELLED",
            known=[slot],
        )

        actions = plan(occurrences, known={slot: event(start=utc(2026, 10, 17, 18), end=utc(2026, 10, 17, 20))})

        # The other occurrences of the series are new
        self.assertEqual([action for action in actions if not isinstance(action, Create)], [Cancel(slot)])

    def test_occurrence_moved_outside_the_window_is_not_cancelled(self):
        later = occurrence(start=NOW + WINDOW + timedelta(days=5), end=NOW + WINDOW + timedelta(days=5, hours=2))

        actions = plan([later], known={("meeting-1", ""): event()})

        self.assertEqual([type(action) for action in actions], [Update])

    def test_other_occurrences_are_not_cancelled(self):
        self.assertEqual(
            plan([occurrence()], known={("meeting-1", ""): event(), ("meeting-2", ""): event()}),
            [Cancel(("meeting-2", ""))],
        )

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
        self.assertEqual(
            details(occurrence(location="  \n", url="https://example.com")).location, "https://example.com"
        )

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


if __name__ == "__main__":
    unittest.main()
