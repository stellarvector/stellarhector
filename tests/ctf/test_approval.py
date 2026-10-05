import unittest

from ctf import approval
from ctf.buttons import Decision
from tests.factories import utc


class ApprovalCardTextTest(unittest.TestCase):
    def test_shows_who_wants_to_join_with_their_roles_server_join_date_and_ctfs_joined_before(self):
        self.assertEqual(
            approval.approval_card("Foo CTF", 42, [11, 12], utc(2025, 9, 1, 12), 3),
            ":raising_hand: <@42> wants to join **Foo CTF**\n"
            "**Roles:** <@&11>, <@&12>\n"
            "**On the server since:** <t:1756728000:D> (<t:1756728000:R>)\n"
            "**CTFs joined before:** 3",
        )

    def test_someone_without_roles_or_known_server_join_date(self):
        card = approval.approval_card("*Foo* CTF", 42, [], None, 0)

        self.assertEqual(
            card,
            ":raising_hand: <@42> wants to join **\\*Foo\\* CTF**\n"
            "**Roles:** none\n"
            "**On the server since:** unknown\n"
            "**CTFs joined before:** 0",
        )


class DecisionLineTest(unittest.TestCase):
    def test_says_who_decided_what(self):
        self.assertEqual(approval.decision_line(Decision.ACCEPT, 7), ":white_check_mark: Accepted by <@7>")
        self.assertEqual(
            approval.decision_line(Decision.ACCEPT_KNOWN, 7), ":white_check_mark: Accepted as known player by <@7>"
        )
        self.assertEqual(approval.decision_line(Decision.DECLINE, 7), ":x: Declined by <@7>")

    def test_adds_what_went_wrong(self):
        self.assertEqual(approval.decision_line(Decision.DECLINE, 7, "DM failed"), ":x: Declined by <@7> (DM failed)")


if __name__ == "__main__":
    unittest.main()
