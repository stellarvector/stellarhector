import unittest

from core.settings import Roles
from ctf import joining
from ctf.joining import JoinOutcome
from ctf.models import PlayerStatus
from tests.factories import ROLES


def decide(*role_names, status=None, closed=False):
    return joining.join_outcome({"@everyone", "sv{member}", *role_names}, ROLES, status, closed)


class DecideTest(unittest.TestCase):
    def test_core_player_joins_right_away(self):
        self.assertEqual(decide("sv{player}", "sv{core-player}"), JoinOutcome.JOINED)

    def test_known_player_joins_right_away(self):
        self.assertEqual(decide("sv{player}", "sv{known-player}"), JoinOutcome.JOINED)

    def test_staff_join_right_away_even_without_a_player_role(self):
        for staff in ("sv{admin}", "sv{manager}", "sv{moderator}"):
            with self.subTest(staff):
                self.assertEqual(decide(staff), JoinOutcome.JOINED)

    def test_plain_player_waits_for_a_moderator(self):
        self.assertEqual(decide("sv{player}"), JoinOutcome.PENDING)

    def test_member_without_a_player_role_must_ask_a_moderator(self):
        self.assertEqual(decide(), JoinOutcome.NO_PLAYER_ROLE)

    def test_someone_who_joined_already_is_told_so(self):
        self.assertEqual(decide("sv{core-player}", status=PlayerStatus.JOINED), JoinOutcome.ALREADY_JOINED)

    def test_someone_who_already_asked_is_still_waiting_and_gets_no_second_card(self):
        self.assertEqual(decide("sv{player}", status=PlayerStatus.PENDING), JoinOutcome.STILL_PENDING)

    def test_nobody_can_join_once_joining_is_closed(self):
        for roles in (("sv{core-player}",), ("sv{player}",), ("sv{admin}",), ()):
            with self.subTest(roles):
                self.assertEqual(decide(*roles, closed=True), JoinOutcome.CLOSED)

    def test_someone_still_waiting_when_joining_closes_is_told_it_is_closed(self):
        self.assertEqual(decide("sv{player}", status=PlayerStatus.PENDING, closed=True), JoinOutcome.CLOSED)

    def test_someone_who_joined_is_told_they_play_even_once_joining_is_closed(self):
        self.assertEqual(decide("sv{core-player}", status=PlayerStatus.JOINED, closed=True), JoinOutcome.ALREADY_JOINED)

    def test_without_a_configured_player_role_a_member_must_ask_a_moderator(self):
        roles = Roles(core_player="sv{core-player}")
        self.assertEqual(joining.join_outcome({"@everyone"}, roles, None, False), JoinOutcome.NO_PLAYER_ROLE)


if __name__ == "__main__":
    unittest.main()
