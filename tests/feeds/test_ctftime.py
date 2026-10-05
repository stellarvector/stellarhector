import asyncio
import json
import unittest
from pathlib import Path

from feeds import ctftime
from tests.factories import utc

FIXTURES = Path(__file__).parent / "fixtures" / "ctftime"


def load(name):
    return json.loads((FIXTURES / name).read_text())


class FakeFetch:
    """Stands in for the HTTP call: answers each request with the next queued response."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    async def __call__(self, url, params=None):
        self.requests.append((url, params))
        return self.responses.pop(0)


def event_data(event_id, start, finish):
    data = load("event.json")
    data.update(id=event_id, start=start, finish=finish)
    return data


class ParseCtftimeIdTest(unittest.TestCase):
    def test_full_url(self):
        self.assertEqual(ctftime.parse_ctftime_id("https://ctftime.org/event/2500/"), 2500)

    def test_without_scheme_or_trailing_slash(self):
        self.assertEqual(ctftime.parse_ctftime_id("ctftime.org/event/2500"), 2500)

    def test_with_www(self):
        self.assertEqual(ctftime.parse_ctftime_id("http://www.ctftime.org/event/2500/"), 2500)

    def test_any_case(self):
        self.assertEqual(ctftime.parse_ctftime_id("https://CTFtime.org/Event/2500"), 2500)

    def test_link_inside_text(self):
        self.assertEqual(ctftime.parse_ctftime_id("Let's play <https://ctftime.org/event/2583> this weekend!"), 2583)

    def test_first_link_wins(self):
        self.assertEqual(ctftime.parse_ctftime_id("ctftime.org/event/1 or ctftime.org/event/2"), 1)

    def test_no_link(self):
        self.assertIsNone(ctftime.parse_ctftime_id("https://ctftime.org/team/12345"))


class GetEventTest(unittest.TestCase):
    def test_parses_the_event(self):
        fetch = FakeFetch(load("event.json"))

        event = asyncio.run(ctftime.get_event(2500, fetch=fetch))

        self.assertEqual(fetch.requests, [("https://ctftime.org/api/v1/events/2500/", None)])
        self.assertEqual(
            event,
            ctftime.Event(
                id=2500,
                title="AlpacaHack Round 5 (Crypto)",
                start=utc(2024, 10, 12, 3, 0),
                finish=utc(2024, 10, 12, 9, 0),
                format="Jeopardy",
                weight=0.0,
                onsite=False,
                url="https://alpacahack.com/ctfs/round-5",
                ctftime_url="https://ctftime.org/event/2500/",
            ),
        )
        self.assertEqual(event.start.utcoffset().total_seconds(), 0)

    def test_unknown_event_is_not_found(self):
        # The fetch answers None for a 404
        self.assertIsNone(asyncio.run(ctftime.get_event(99999999, fetch=FakeFetch(None))))

    def test_event_with_missing_fields_is_an_error(self):
        with self.assertRaises(ctftime.CtftimeError):
            asyncio.run(ctftime.get_event(2500, fetch=FakeFetch({"id": 2500})))


class ListEventsTest(unittest.TestCase):
    def test_parses_every_event(self):
        fetch = FakeFetch(load("events.json"))

        events = asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=fetch))

        self.assertEqual([e.id for e in events], [2503, 2570, 2583])
        self.assertEqual(events[0].weight, 34.3)
        self.assertEqual(events[0].finish, utc(2025, 1, 6))
        self.assertEqual(events[2].title, "HKCERT CTF 2024 (Final Round)")
        self.assertEqual(events[2].format, "Attack-Defense")
        self.assertTrue(events[2].onsite)

    def test_asks_for_events_from_start_on(self):
        fetch = FakeFetch([])

        asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=fetch))

        url, params = fetch.requests[0]
        self.assertEqual(url, "https://ctftime.org/api/v1/events/")
        self.assertEqual(params["start"], 1735689600)  # 2025-01-01T00:00:00Z

    def test_includes_events_that_start_in_range_but_finish_after_it(self):
        # CTFtime's finish filter is on the event's finish, so the client has to ask beyond the range
        fetch = FakeFetch([event_data(1, "2025-02-28T12:00:00+00:00", "2025-03-02T12:00:00+00:00")])

        events = asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=fetch))

        self.assertEqual([e.id for e in events], [1])
        self.assertGreater(fetch.requests[0][1]["finish"], 1740787200)  # 2025-03-01T00:00:00Z

    def test_leaves_out_events_starting_after_the_range(self):
        fetch = FakeFetch(
            [
                event_data(1, "2025-02-28T12:00:00+00:00", "2025-03-02T12:00:00+00:00"),
                event_data(2, "2025-03-01T00:00:00+00:00", "2025-03-02T00:00:00+00:00"),
            ]
        )

        events = asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=fetch))

        self.assertEqual([e.id for e in events], [1])

    def test_pages_until_a_page_is_not_full(self):
        def starting_on(event_id, day):
            return event_data(event_id, f"2025-01-{day:02}T10:00:00+00:00", f"2025-01-{day:02}T20:00:00+00:00")

        # A full first page whose last events share a start time, then CTFtime is asked again from that start on
        first_page = [starting_on(i, 2) for i in range(1, ctftime.PAGE_SIZE - 1)]
        first_page += [starting_on(100, 3), starting_on(101, 3)]
        second_page = [starting_on(100, 3), starting_on(101, 3), starting_on(102, 3), starting_on(103, 4)]
        fetch = FakeFetch(first_page, second_page)

        events = asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=fetch))

        self.assertEqual(len(fetch.requests), 2)
        self.assertEqual(fetch.requests[0][1]["limit"], ctftime.PAGE_SIZE)
        self.assertEqual(fetch.requests[1][1]["start"], 1735898400)  # 2025-01-03T10:00:00Z
        self.assertEqual([e.id for e in events], list(range(1, ctftime.PAGE_SIZE - 1)) + [100, 101, 102, 103])

    def test_stops_paging_once_past_the_range(self):
        # The margin past the range can fill a page too; nothing after that page is needed
        first_page = [
            event_data(i, "2025-01-02T10:00:00+00:00", "2025-01-02T20:00:00+00:00") for i in range(1, ctftime.PAGE_SIZE)
        ]
        first_page.append(event_data(500, "2025-03-05T10:00:00+00:00", "2025-03-05T20:00:00+00:00"))
        fetch = FakeFetch(first_page)

        events = asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=fetch))

        self.assertEqual(len(fetch.requests), 1)
        self.assertEqual(len(events), ctftime.PAGE_SIZE - 1)

    def test_missing_list_is_an_error(self):
        # A 404 on the list endpoint means the API moved, not that there are no events
        with self.assertRaises(ctftime.CtftimeError):
            asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=FakeFetch(None)))

    def test_unexpected_response_is_an_error(self):
        with self.assertRaises(ctftime.CtftimeError):
            asyncio.run(ctftime.list_events(utc(2025, 1, 1), utc(2025, 3, 1), fetch=FakeFetch({"error": "x"})))


if __name__ == "__main__":
    unittest.main()
