import unittest

from cogs.ctftime_feed import check_reply
from feeds.ctftime_check import CtftimeCheckResult


class CheckReplyTest(unittest.TestCase):
    def test_reply_counts_the_checked_ctfs_and_alerts(self):
        reply = check_reply(CtftimeCheckResult(checked=3, alerts=1))

        self.assertEqual(reply, ":white_check_mark: CTFtime checked: 3 CTFs checked, 1 alert posted.")

    def test_reply_mentions_ctfs_ctftime_could_not_tell_about(self):
        reply = check_reply(CtftimeCheckResult(checked=1, alerts=2, skipped=2))

        self.assertEqual(
            reply,
            ":warning: CTFtime checked: 1 CTF checked, 2 alerts posted. 2 CTFs were skipped because"
            " CTFtime could not be reached; they are tried again on the next check.",
        )


if __name__ == "__main__":
    unittest.main()
