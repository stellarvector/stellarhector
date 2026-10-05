import unittest
from dataclasses import replace

from ctf import join_message
from ctf.models import Ctf
from feeds.calendar.sessions import Session
from tests.factories import utc

CTF = Ctf(
    name="Foo CTF",
    ctftime_id=None,
    start=None,
    finish=None,
    role_id=1,
    category_id=2,
    main_channel_id=3,
    bot_channel_id=4,
    guide_message_id=5,
    id=9,
    join_channel_id=6,
    join_message_id=7,
    overview_message_id=None,
    last_call_at=None,
    released_at=None,
    locked_at=None,
    archived_at=None,
    removal_reminded_at=None,
    removed_at=None,
)
# 2026-10-10 08:00 and 2026-10-12 08:00 UTC
START, FINISH = utc(2026, 10, 10, 8), utc(2026, 10, 12, 8)


class JoinMessageTest(unittest.TestCase):
    def test_ctf_without_ctftime_or_players_shows_its_name_and_that_nobody_plays_yet(self):
        self.assertEqual(
            join_message.join_message(CTF, [], []),
            "## :zap: Foo CTF\n**Playing:** nobody yet, click **Join** to be the first",
        )

    def test_shows_the_ctftime_link_with_start_and_finish(self):
        ctf = replace(CTF, ctftime_id=3352, start=START, finish=FINISH)

        self.assertEqual(
            join_message.join_message(ctf, [], []),
            "## :zap: Foo CTF\n"
            "<https://ctftime.org/event/3352/>\n"
            "From <t:1791619200:F> to <t:1791792000:F>\n"
            "**Playing:** nobody yet, click **Join** to be the first",
        )

    def test_lists_the_on_campus_sessions(self):
        ctf = replace(CTF, ctftime_id=3352, start=START, finish=FINISH)
        sessions = [Session("CTF night", utc(2026, 10, 10, 17), utc(2026, 10, 10, 22))]

        self.assertIn(
            "**On campus:**\n- CTF night: <t:1791651600:F> to <t:1791669600:F>\n",
            join_message.join_message(ctf, [], sessions),
        )

    def test_lists_the_players_with_their_count(self):
        self.assertTrue(join_message.join_message(CTF, [42, 43], []).endswith("**Playing (2):** <@42>, <@43>"))

    def test_lists_at_most_20_players_and_counts_the_rest(self):
        message = join_message.join_message(CTF, list(range(1, 26)), [])

        self.assertTrue(
            message.endswith("**Playing (25):** " + ", ".join(f"<@{i}>" for i in range(1, 21)) + " and 5 more")
        )

    def test_after_the_last_call_it_says_last_call(self):
        ctf = replace(CTF, last_call_at=utc(2026, 10, 9, 8))

        self.assertEqual(
            join_message.join_message(ctf, [42], []), "## :rotating_light: Last call: Foo CTF\n**Playing (1):** <@42>"
        )

    def test_once_released_it_says_joining_is_closed_and_the_ctf_is_open_to_all_members(self):
        ctf = replace(
            CTF,
            ctftime_id=3352,
            start=START,
            finish=FINISH,
            last_call_at=utc(2026, 10, 9, 8),
            released_at=utc(2026, 10, 13, 8),
        )
        sessions = [Session("CTF night", utc(2026, 10, 10, 17), utc(2026, 10, 10, 22))]

        self.assertEqual(
            join_message.join_message(ctf, [42], sessions),
            "## :unlock: Foo CTF\n"
            "<https://ctftime.org/event/3352/>\n"
            "From <t:1791619200:F> to <t:1791792000:F>\n"
            "**Playing (1):** <@42>\n"
            "**Joining is closed:** the CTF is open to all members, see <#3>",
        )

    def test_once_released_without_players_it_does_not_ask_to_join(self):
        self.assertEqual(
            join_message.join_message(replace(CTF, released_at=utc(2026, 10, 13, 8)), [], []),
            "## :unlock: Foo CTF\n**Playing:** nobody\n**Joining is closed:** the CTF is open to all members, see <#3>",
        )

    def test_name_shows_as_typed_without_markdown(self):
        self.assertTrue(
            join_message.join_message(replace(CTF, name="*Foo* CTF"), [], []).startswith("## :zap: \\*Foo\\* CTF\n")
        )


if __name__ == "__main__":
    unittest.main()
