import asyncio
import sqlite3
import unittest
from datetime import UTC, datetime, timedelta

import discord

from core import db
from feeds.calendar import events
from tests.factories import use_temporary_database
from tests.feeds.calendar.factories import NOW, WINDOW, feed, occurrence, plan

EVENT_URL = "https://discord.com/events/1/2"


def fields(embed):
    return {field.name: field.value for field in embed.fields}


class AnnouncementTest(unittest.TestCase):
    def announce(self, meeting=None, ping_role=None):
        action = plan([meeting or occurrence(location="Room 1", description="Bring snacks")])[0]
        return events.announcement(action, EVENT_URL, ping_role)

    def test_embed_shows_the_event(self):
        content, embed, _ = self.announce()

        self.assertEqual(embed.title, "Weekly meeting")
        self.assertEqual(embed.url, EVENT_URL)
        self.assertEqual(embed.description, "Bring snacks")
        self.assertEqual(
            fields(embed),
            {
                "Start": "<t:1791655200:F> (<t:1791655200:R>)",
                "End": "<t:1791662400:F> (<t:1791662400:R>)",
                "Location": "Room 1",
                "Event": f"[Open in Discord]({EVENT_URL})",
            },
        )

    def test_running_event_shows_its_real_start(self):
        running = occurrence(start=NOW - timedelta(hours=1), end=NOW + timedelta(hours=1))

        _, embed, _ = self.announce(running)

        start = int((NOW - timedelta(hours=1)).timestamp())
        self.assertEqual(fields(embed)["Start"], f"<t:{start}:F> (<t:{start}:R>)")

    def test_long_description_is_an_excerpt(self):
        _, embed, _ = self.announce(occurrence(description="x" * 2000))

        self.assertEqual(embed.description, "x" * (events.EXCERPT_LIMIT - 1) + "…")

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


class FakeEvent:
    """A Discord scheduled event the fake guild has; delete takes it out of the guild."""

    def __init__(
        self,
        guild,
        event_id,
        name,
        start_time,
        end_time,
        location,
        description=None,
        status=discord.EventStatus.scheduled,
    ):
        self.guild = guild
        self.id = event_id
        self.name = name
        self.start_time = start_time
        self.end_time = end_time
        self.location = location
        self.description = description
        self.status = status
        self.url = f"https://discord.com/events/1/{event_id}"

    async def delete(self):
        self.guild.events.remove(self)


class FakeGuild:
    """Creates and lists FakeEvents; create_scheduled_event waits for release when it is set."""

    def __init__(self):
        self.events = []
        self.next_id = 1
        self.creating = asyncio.Event()
        self.release = None

    async def fetch_scheduled_events(self, with_counts=True):
        return list(self.events)

    async def create_scheduled_event(self, name, start_time, end_time, location, description=None, **kwargs):
        self.creating.set()
        if self.release is not None:
            await self.release.wait()
        event = FakeEvent(
            self,
            self.next_id,
            name,
            start_time,
            end_time,
            location,
            None if description is discord.utils.MISSING else description,
        )
        self.next_id += 1
        self.events.append(event)
        return event


def ics_time(moment):
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


class SyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)
        self.guild = FakeGuild()
        self.now = datetime.now(UTC).replace(microsecond=0)

    def feed_with_meeting(self, start, end):
        body = f"UID:meeting-1\nDTSTART:{ics_time(start)}\nDTEND:{ics_time(end)}\nSUMMARY:Weekly meeting"

        async def fetch(url):
            return feed(body)

        return fetch

    async def sync(self, fetch):
        return await events.sync(
            self.guild, "https://calendar.example/feed.ics", "Europe/Brussels", WINDOW, fetch=fetch
        )

    def stored_event_ids(self):
        with db.transaction() as conn:
            return [
                row["discord_event_id"] for row in conn.execute("SELECT discord_event_id FROM calendar_occurrences")
            ]

    async def test_sync_stopped_while_creating_is_not_created_again_by_the_next_sync(self):
        fetch = self.feed_with_meeting(self.now + timedelta(days=2), self.now + timedelta(days=2, hours=2))
        self.guild.release = asyncio.Event()

        stopped = asyncio.create_task(self.sync(fetch))
        await self.guild.creating.wait()
        stopped.cancel()
        next_sync = asyncio.create_task(self.sync(fetch))
        await asyncio.sleep(0)
        self.guild.release.set()
        await next_sync
        with self.assertRaises(asyncio.CancelledError):
            await stopped

        self.assertEqual(len(self.guild.events), 1)
        self.assertEqual(self.stored_event_ids(), [self.guild.events[0].id])

    async def test_running_event_moved_to_later_is_replaced_by_one_at_the_new_start(self):
        start = self.now + timedelta(hours=3)
        await self.sync(self.feed_with_meeting(self.now - timedelta(hours=1), self.now + timedelta(hours=1)))
        running = self.guild.events[0]
        running.status = discord.EventStatus.active
        running.start_time = self.now - timedelta(minutes=10)

        summary = await self.sync(self.feed_with_meeting(start, start + timedelta(hours=2)))

        self.assertEqual(summary.updated, 1)
        self.assertEqual([event.start_time for event in self.guild.events], [start])
        self.assertNotIn(running, self.guild.events)
        self.assertEqual(self.stored_event_ids(), [self.guild.events[0].id])

    async def test_event_is_deleted_again_when_it_cannot_be_remembered(self):
        # An event the bot doesn't remember would be created again on every sync
        with db.transaction() as conn:
            conn.execute(
                "CREATE TRIGGER refuse BEFORE INSERT ON calendar_occurrences "
                "BEGIN SELECT RAISE(ABORT, 'disk full'); END"
            )
        fetch = self.feed_with_meeting(self.now + timedelta(days=2), self.now + timedelta(days=2, hours=2))

        with self.assertRaises(sqlite3.DatabaseError):
            await self.sync(fetch)

        self.assertEqual(self.guild.events, [])


if __name__ == "__main__":
    unittest.main()
