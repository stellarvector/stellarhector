import asyncio
import unittest
from datetime import date

from feeds import ctftime_table
from feeds.calendar.sessions import Session
from feeds.ctftime import CtftimeError, Event
from tests.factories import utc

TZ = "Europe/Brussels"


def event(
    event_id=1,
    title="Foo CTF 2026",
    start=utc(2026, 11, 7, 10),
    finish=utc(2026, 11, 9, 10),
    format="Jeopardy",
    weight=24.7,
    onsite=False,
):
    return Event(
        id=event_id,
        title=title,
        start=start,
        finish=finish,
        format=format,
        weight=weight,
        onsite=onsite,
        url="https://foo.example",
        ctftime_url=f"https://ctftime.org/event/{event_id}/",
    )


def session(start, end):
    return Session(title="CTF night", start=start, end=end)


def no_sessions():
    return {}


def code_part(line):
    """The fixed-width text between the backticks."""
    return line.split("`")[1]


class ParseStartMonthTest(unittest.TestCase):
    def test_default_is_this_month(self):
        self.assertEqual(ctftime_table.parse_start_month(None, date(2026, 10, 3)), (2026, 10))
        self.assertEqual(ctftime_table.parse_start_month(None, date(2026, 12, 31)), (2026, 12))

    def test_year_and_month(self):
        self.assertEqual(ctftime_table.parse_start_month("2027-02", date(2026, 10, 3)), (2027, 2))

    def test_month_number_later_this_year(self):
        self.assertEqual(ctftime_table.parse_start_month("11", date(2026, 10, 3)), (2026, 11))

    def test_month_number_this_month(self):
        self.assertEqual(ctftime_table.parse_start_month("10", date(2026, 10, 3)), (2026, 10))

    def test_month_number_already_past_is_next_year(self):
        self.assertEqual(ctftime_table.parse_start_month("2", date(2026, 10, 3)), (2027, 2))

    def test_surrounding_spaces_are_ignored(self):
        self.assertEqual(ctftime_table.parse_start_month(" 2027-2 ", date(2026, 10, 3)), (2027, 2))

    def test_invalid(self):
        for value in ["13", "0", "2026-13", "november", "2026/11", ""]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ctftime_table.parse_start_month(value, date(2026, 10, 3))

    def test_year_out_of_range(self):
        for value in ["0000-05", "9999-01"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ctftime_table.parse_start_month(value, date(2026, 10, 3))

    def test_last_supported_year_has_a_date_range(self):
        start = ctftime_table.parse_start_month("9998-12", date(2026, 10, 3))
        ctftime_table.date_range(ctftime_table.months(start, 12), TZ)


class MonthsTest(unittest.TestCase):
    def test_runs_over_the_year_end(self):
        self.assertEqual(ctftime_table.months((2026, 11), 3), [(2026, 11), (2026, 12), (2027, 1)])

    def test_range_is_in_the_timezone(self):
        start, finish = ctftime_table.date_range([(2026, 11), (2026, 12)], TZ)

        self.assertEqual(start, utc(2026, 10, 31, 23))
        self.assertEqual(finish, utc(2026, 12, 31, 23))


class FormatLineTest(unittest.TestCase):
    def test_columns(self):
        line = ctftime_table.format_line(event(), TZ)

        self.assertEqual(
            line,
            "`Sat 07/11 11:00 -> Mon 09/11 11:00  Foo CTF 2026          Jeopardy   24.7  online`"
            " [ctftime](<https://ctftime.org/event/1/>) ⭐",
        )

    def test_every_line_has_the_same_width(self):
        lines = [
            ctftime_table.format_line(event(title="X"), TZ),
            ctftime_table.format_line(event(title="A very long CTF name that goes on and on"), TZ),
            ctftime_table.format_line(event(format="Attack-Defense", weight=100.0, onsite=True), TZ),
            ctftime_table.format_line(event(format="Hack quest", weight=0), TZ),
        ]

        self.assertEqual(len({len(code_part(line)) for line in lines}), 1)

    def test_long_name_is_cut_with_ellipsis(self):
        line = ctftime_table.format_line(event(title="A very long CTF name that goes on and on"), TZ)

        dates = len("Sat 07/11 11:00 -> Mon 09/11 11:00  ")
        name = code_part(line)[dates : dates + ctftime_table.NAME_WIDTH]
        self.assertEqual(name, "A very long CTF nam…")

    def test_name_that_fits_exactly_is_not_cut(self):
        title = "x" * ctftime_table.NAME_WIDTH
        self.assertIn(title + "  ", ctftime_table.format_line(event(title=title), TZ))

    def test_backticks_and_newlines_in_name_cannot_break_the_code(self):
        line = ctftime_table.format_line(event(title="Foo`s\nCTF"), TZ)

        self.assertEqual(line.count("`"), 2)
        self.assertNotIn("\n", line)

    def test_attack_defense_is_abbreviated(self):
        self.assertIn("  A/D    ", ctftime_table.format_line(event(format="Attack-Defense"), TZ))

    def test_onsite(self):
        self.assertIn("onsite`", ctftime_table.format_line(event(onsite=True), TZ))

    def test_start_and_finish_are_shown_in_the_timezone(self):
        # CTFtime's times are UTC; Brussels is UTC+2 in summer time and UTC+1 after it
        line = ctftime_table.format_line(event(start=utc(2026, 10, 9, 16), finish=utc(2026, 10, 30, 23, 30)), TZ)

        self.assertTrue(line.startswith("`Fri 09/10 18:00 -> Sat 31/10 00:30  "))

    def test_finish_at_midnight_shows_midnight(self):
        line = ctftime_table.format_line(event(start=utc(2026, 11, 7, 10), finish=utc(2026, 11, 9, 23)), TZ)

        self.assertTrue(line.startswith("`Sat 07/11 11:00 -> Tue 10/11 00:00  "))

    def test_mark_goes_between_code_and_link(self):
        line = ctftime_table.format_line(event(weight=0), TZ, ctftime_table.IN_CALENDAR)

        self.assertTrue(line.endswith("online` ✅ [ctftime](<https://ctftime.org/event/1/>)"))

    def test_online_rated_jeopardy_ctf_gets_a_star_at_the_very_end(self):
        line = ctftime_table.format_line(event(), TZ, ctftime_table.IN_CALENDAR)

        self.assertTrue(line.endswith("` ✅ [ctftime](<https://ctftime.org/event/1/>) ⭐"))

    def test_no_star_for_onsite_unrated_or_other_formats(self):
        for other in (event(onsite=True), event(weight=0), event(format="Attack-Defense")):
            with self.subTest(other):
                self.assertTrue(
                    ctftime_table.format_line(other, TZ).endswith("[ctftime](<https://ctftime.org/event/1/>)")
                )


class MarkTest(unittest.TestCase):
    def test_no_session(self):
        self.assertIsNone(ctftime_table.mark(event(), []))

    def test_overlapping_session(self):
        sessions = [session(utc(2026, 11, 7, 17), utc(2026, 11, 7, 22))]
        self.assertEqual(ctftime_table.mark(event(), sessions), ctftime_table.IN_CALENDAR)

    def test_session_outside_the_ctf(self):
        sessions = [session(utc(2026, 11, 14, 17), utc(2026, 11, 14, 22))]
        self.assertEqual(ctftime_table.mark(event(), sessions), ctftime_table.NOT_OVERLAPPING)

    def test_session_touching_the_end_does_not_overlap(self):
        sessions = [session(utc(2026, 11, 9, 10), utc(2026, 11, 9, 12))]
        self.assertEqual(ctftime_table.mark(event(), sessions), ctftime_table.NOT_OVERLAPPING)

    def test_one_session_outside_is_enough_for_a_warning(self):
        sessions = [
            session(utc(2026, 11, 7, 17), utc(2026, 11, 7, 22)),
            session(utc(2026, 11, 14, 17), utc(2026, 11, 14, 22)),
        ]
        self.assertEqual(ctftime_table.mark(event(), sessions), ctftime_table.NOT_OVERLAPPING)


class TableLinesTest(unittest.TestCase):
    def test_header_per_month_first_validate_then_preview(self):
        lines = ctftime_table.table_lines([], [(2026, 11), (2026, 12), (2027, 1)], TZ)

        headers = [line for line in lines if line.startswith("**")]
        self.assertEqual(
            headers,
            [
                "**November 2026** (validate)",
                "**December 2026** (preview)",
                "**January 2027** (preview)",
            ],
        )

    def test_empty_month_says_so(self):
        lines = ctftime_table.table_lines([], [(2026, 11)], TZ)

        self.assertEqual(lines, ["**November 2026** (validate)", ctftime_table.NO_EVENTS])

    def test_events_sorted_by_start_within_their_month(self):
        events = [
            event(3, start=utc(2026, 12, 5), finish=utc(2026, 12, 6)),
            event(2, start=utc(2026, 11, 20), finish=utc(2026, 11, 21)),
            event(1, start=utc(2026, 11, 7), finish=utc(2026, 11, 8)),
        ]

        lines = ctftime_table.table_lines(events, [(2026, 11), (2026, 12)], TZ)

        self.assertEqual(lines[0], "**November 2026** (validate)")
        self.assertIn("event/1/", lines[1])
        self.assertIn("event/2/", lines[2])
        self.assertEqual(lines[3], "")
        self.assertEqual(lines[4], "**December 2026** (preview)")
        self.assertIn("event/3/", lines[5])

    def test_month_is_taken_from_the_start_in_the_timezone(self):
        events = [event(1, start=utc(2026, 11, 30, 23, 30), finish=utc(2026, 12, 1, 12))]

        lines = ctftime_table.table_lines(events, [(2026, 11), (2026, 12)], TZ)

        self.assertEqual(lines[1], ctftime_table.NO_EVENTS)
        self.assertIn("event/1/", lines[4])

    def test_marks_are_looked_up_by_event_id(self):
        lines = ctftime_table.table_lines([event(1)], [(2026, 11)], TZ, {1: ctftime_table.NOT_OVERLAPPING})

        self.assertIn("` ⚠️ [ctftime]", lines[1])


class SplitMessagesTest(unittest.TestCase):
    def test_short_table_is_one_message(self):
        self.assertEqual(ctftime_table.split_messages(["a", "b"]), ["a\nb"])

    def test_splits_between_lines_under_the_limit(self):
        lines = [f"{i:03}" + "x" * 96 for i in range(50)]  # 100 characters each

        messages = ctftime_table.split_messages(lines, limit=2000)

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= 2000 for message in messages))
        self.assertEqual("\n".join(messages).split("\n"), lines)

    def test_message_exactly_at_the_limit(self):
        lines = ["x" * 9, "y" * 10]

        self.assertEqual(ctftime_table.split_messages(lines, limit=20), ["x" * 9 + "\n" + "y" * 10])
        self.assertEqual(ctftime_table.split_messages(lines, limit=19), ["x" * 9, "y" * 10])

    def test_blank_lines_are_not_left_at_the_edges(self):
        messages = ctftime_table.split_messages(["a" * 10, "", "b" * 10], limit=11)

        self.assertEqual(messages, ["a" * 10, "b" * 10])

    def test_header_moves_along_with_its_first_ctf(self):
        lines = ["a" * 10, "", "**Dec**", "b" * 10]

        messages = ctftime_table.split_messages(lines, limit=20)

        self.assertEqual(messages, ["a" * 10, "**Dec**\n" + "b" * 10])

    def test_real_table_stays_under_discords_limit(self):
        events = [
            event(i, title=f"CTF number {i}", start=utc(2026, 11, 1 + i % 28, 12), finish=utc(2026, 11, 2 + i % 28))
            for i in range(60)
        ]

        messages = ctftime_table.split_messages(ctftime_table.table_lines(events, [(2026, 11)], TZ))

        self.assertGreater(len(messages), 1)
        self.assertTrue(all(len(message) <= ctftime_table.MESSAGE_LIMIT for message in messages))


class FakeChannel:
    def __init__(self):
        self.sent = []

    async def send(self, content, **kwargs):
        self.sent.append(content)


class PostTableTest(unittest.TestCase):
    def test_ctfs_with_calendar_sessions_are_marked(self):
        async def list_events(start, finish):
            return [event(1), event(2, start=utc(2026, 11, 14, 10), finish=utc(2026, 11, 15, 10)), event(3)]

        def linked_sessions():
            return {
                1: [session(utc(2026, 11, 7, 17), utc(2026, 11, 7, 22))],
                2: [session(utc(2026, 11, 21, 17), utc(2026, 11, 21, 22))],
            }

        channel = FakeChannel()
        asyncio.run(
            ctftime_table.post_table(
                channel, (2026, 11), 1, TZ, list_events=list_events, linked_sessions=linked_sessions
            )
        )

        lines = channel.sent[0].splitlines()
        self.assertIn("` ✅ [ctftime](<https://ctftime.org/event/1/>)", lines[1])
        self.assertIn("` [ctftime](<https://ctftime.org/event/3/>)", lines[2])
        self.assertIn("` ⚠️ [ctftime](<https://ctftime.org/event/2/>)", lines[3])

    def test_fetches_the_whole_range_and_posts_every_message(self):
        requested = []

        async def list_events(start, finish):
            requested.append((start, finish))
            return [event(1)]

        channel = FakeChannel()
        count = asyncio.run(
            ctftime_table.post_table(channel, (2026, 11), 2, TZ, list_events=list_events, linked_sessions=no_sessions)
        )

        self.assertEqual(count, 1)
        self.assertEqual(requested, [(utc(2026, 10, 31, 23), utc(2026, 12, 31, 23))])
        self.assertEqual(len(channel.sent), 1)
        self.assertTrue(channel.sent[0].startswith("**November 2026** (validate)\n`Sat 07/11 11:00"))
        self.assertIn("**December 2026** (preview)", channel.sent[0])

    def test_finished_ctfs_are_hidden_when_asked(self):
        async def list_events(start, finish):
            return [
                event(1, start=utc(2026, 11, 1, 10), finish=utc(2026, 11, 3, 10)),
                event(2, start=utc(2026, 11, 2, 10), finish=utc(2026, 11, 5, 10)),
                event(3, start=utc(2026, 11, 20, 10), finish=utc(2026, 11, 21, 10)),
            ]

        def post(hide_finished_at):
            channel = FakeChannel()
            count = asyncio.run(
                ctftime_table.post_table(
                    channel,
                    (2026, 11),
                    1,
                    TZ,
                    hide_finished_at=hide_finished_at,
                    list_events=list_events,
                    linked_sessions=no_sessions,
                )
            )
            return count, channel.sent[0]

        count, table = post(utc(2026, 11, 4))
        self.assertEqual(count, 2)
        self.assertNotIn("event/1/", table)
        self.assertIn("event/2/", table)

        count, table = post(None)
        self.assertEqual(count, 3)
        self.assertIn("event/1/", table)

    def test_ctftime_error_posts_nothing(self):
        async def list_events(start, finish):
            raise CtftimeError("down")

        channel = FakeChannel()
        with self.assertRaises(CtftimeError):
            asyncio.run(
                ctftime_table.post_table(
                    channel, (2026, 11), 2, TZ, list_events=list_events, linked_sessions=no_sessions
                )
            )
        self.assertEqual(channel.sent, [])


if __name__ == "__main__":
    unittest.main()
