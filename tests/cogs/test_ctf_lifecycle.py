import unittest

from cogs.ctf_lifecycle import lock_notice
from ctf.lock import Locked
from tests.factories import stored_ctf


class LockNoticeTest(unittest.TestCase):
    def test_says_it_is_locked_and_archived_and_how_to_remove_it(self):
        self.assertEqual(
            lock_notice(Locked(stored_ctf(), None)),
            "Locked and archived. Remove it with `/remove-ctf` when you're ready.",
        )

    def test_after_a_failed_archive_gives_the_error_and_says_to_run_archive_ctf(self):
        self.assertEqual(
            lock_notice(Locked(stored_ctf(), RuntimeError("push rejected"))),
            ":warning: Locked, but archiving failed: `RuntimeError: push rejected`\nRun `/archive-ctf` to try again.",
        )


if __name__ == "__main__":
    unittest.main()
