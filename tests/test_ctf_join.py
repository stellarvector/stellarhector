import unittest
from dataclasses import replace
from datetime import datetime, timezone

from utils import ctf_join, ctfs
from utils.ctftime_check import Session
from utils.ctf_join import Decision, Outcome

ROLES = ctf_join.JoinRoles(trusted=frozenset({"sv{core-player}", "sv{known-player}", "sv{admin}", "sv{manager}",
                                              "sv{moderator}"}),
                           player="sv{player}")


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


CTF = ctfs.Ctf(name="Foo CTF", ctftime_id=None, start=None, finish=None, role_id=1, category_id=2, main_channel_id=3,
               bot_channel_id=4, guide_message_id=5, id=9, join_channel_id=6, join_message_id=7,
               overview_message_id=None, last_call_at=None, released_at=None, locked_at=None, archived_at=None,
               removal_reminded_at=None, removed_at=None)
# 2026-10-10 08:00 and 2026-10-12 08:00 UTC
START, FINISH = utc(2026, 10, 10, 8), utc(2026, 10, 12, 8)


def decide(*role_names, status=None, closed=False):
    return ctf_join.decide({"@everyone", "sv{member}", *role_names}, ROLES, status, closed)


class DecideTest(unittest.TestCase):
    def test_core_player_joins_right_away(self):
        self.assertEqual(decide("sv{player}", "sv{core-player}"), Outcome.JOINED)

    def test_known_player_joins_right_away(self):
        self.assertEqual(decide("sv{player}", "sv{known-player}"), Outcome.JOINED)

    def test_staff_join_right_away_even_without_a_player_role(self):
        for staff in ("sv{admin}", "sv{manager}", "sv{moderator}"):
            with self.subTest(staff):
                self.assertEqual(decide(staff), Outcome.JOINED)

    def test_plain_player_waits_for_a_moderator(self):
        self.assertEqual(decide("sv{player}"), Outcome.PENDING)

    def test_member_without_a_player_role_must_ask_a_moderator(self):
        self.assertEqual(decide(), Outcome.NO_PLAYER_ROLE)

    def test_someone_who_joined_already_is_told_so(self):
        self.assertEqual(decide("sv{core-player}", status="joined"), Outcome.ALREADY_JOINED)

    def test_someone_who_already_asked_is_still_waiting_and_gets_no_second_card(self):
        self.assertEqual(decide("sv{player}", status="pending"), Outcome.STILL_PENDING)

    def test_nobody_can_join_once_joining_is_closed(self):
        for roles in (("sv{core-player}",), ("sv{player}",), ("sv{admin}",), ()):
            with self.subTest(roles):
                self.assertEqual(decide(*roles, closed=True), Outcome.CLOSED)

    def test_someone_still_waiting_when_joining_closes_is_told_it_is_closed(self):
        self.assertEqual(decide("sv{player}", status="pending", closed=True), Outcome.CLOSED)

    def test_someone_who_joined_is_told_they_play_even_once_joining_is_closed(self):
        self.assertEqual(decide("sv{core-player}", status="joined", closed=True), Outcome.ALREADY_JOINED)

    def test_without_a_configured_player_role_a_member_must_ask_a_moderator(self):
        roles = ctf_join.JoinRoles(trusted=frozenset({"sv{core-player}"}), player=None)
        self.assertEqual(ctf_join.decide({"@everyone"}, roles, None, False), Outcome.NO_PLAYER_ROLE)


class JoinMessageTest(unittest.TestCase):
    def test_ctf_without_ctftime_or_players_shows_its_name_and_that_nobody_plays_yet(self):
        self.assertEqual(ctf_join.join_message(CTF, [], []),
                         "## :zap: Foo CTF\n"
                         "**Playing:** nobody yet, click **Join** to be the first")

    def test_shows_the_ctftime_link_with_start_and_finish(self):
        ctf = replace(CTF, ctftime_id=3352, start=START, finish=FINISH)

        self.assertEqual(ctf_join.join_message(ctf, [], []),
                         "## :zap: Foo CTF\n"
                         "<https://ctftime.org/event/3352/>\n"
                         "From <t:1791619200:F> to <t:1791792000:F>\n"
                         "**Playing:** nobody yet, click **Join** to be the first")

    def test_lists_the_on_campus_sessions(self):
        ctf = replace(CTF, ctftime_id=3352, start=START, finish=FINISH)
        sessions = [Session("CTF night", utc(2026, 10, 10, 17), utc(2026, 10, 10, 22))]

        self.assertIn("**On campus:**\n- CTF night: <t:1791651600:F> to <t:1791669600:F>\n",
                      ctf_join.join_message(ctf, [], sessions))

    def test_lists_the_players_with_their_count(self):
        self.assertTrue(ctf_join.join_message(CTF, [42, 43], []).endswith("**Playing (2):** <@42>, <@43>"))

    def test_lists_at_most_20_players_and_counts_the_rest(self):
        message = ctf_join.join_message(CTF, list(range(1, 26)), [])

        self.assertTrue(message.endswith(
            "**Playing (25):** " + ", ".join(f"<@{i}>" for i in range(1, 21)) + " and 5 more"))

    def test_after_the_last_call_it_says_last_call(self):
        ctf = replace(CTF, last_call_at=utc(2026, 10, 9, 8))

        self.assertEqual(ctf_join.join_message(ctf, [42], []),
                         "## :rotating_light: Last call: Foo CTF\n"
                         "**Playing (1):** <@42>")

    def test_name_shows_as_typed_without_markdown(self):
        self.assertTrue(ctf_join.join_message(replace(CTF, name="*Foo* CTF"), [], []).startswith(
            "## :zap: \\*Foo\\* CTF\n"))


class ApprovalCardTextTest(unittest.TestCase):
    def test_shows_who_wants_to_join_with_their_roles_server_join_date_and_ctfs_joined_before(self):
        self.assertEqual(ctf_join.approval_card("Foo CTF", 42, [11, 12], utc(2025, 9, 1, 12), 3),
                         ":raising_hand: <@42> wants to join **Foo CTF**\n"
                         "**Roles:** <@&11>, <@&12>\n"
                         "**On the server since:** <t:1756728000:D> (<t:1756728000:R>)\n"
                         "**CTFs joined before:** 3")

    def test_someone_without_roles_or_known_server_join_date(self):
        card = ctf_join.approval_card("*Foo* CTF", 42, [], None, 0)

        self.assertEqual(card, ":raising_hand: <@42> wants to join **\\*Foo\\* CTF**\n"
                               "**Roles:** none\n"
                               "**On the server since:** unknown\n"
                               "**CTFs joined before:** 0")


class DecisionLineTest(unittest.TestCase):
    def test_says_who_decided_what(self):
        self.assertEqual(ctf_join.decision_line(Decision.ACCEPT, 7), ":white_check_mark: Accepted by <@7>")
        self.assertEqual(ctf_join.decision_line(Decision.ACCEPT_KNOWN, 7),
                         ":white_check_mark: Accepted as known player by <@7>")
        self.assertEqual(ctf_join.decision_line(Decision.DECLINE, 7), ":x: Declined by <@7>")

    def test_adds_what_went_wrong(self):
        self.assertEqual(ctf_join.decision_line(Decision.DECLINE, 7, "DM failed"), ":x: Declined by <@7> (DM failed)")
