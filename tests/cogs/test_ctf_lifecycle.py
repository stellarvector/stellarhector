import unittest

from cogs.ctf_lifecycle import lock_notice, with_credentials_note
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


class CredentialsNoteTest(unittest.TestCase):
    def test_says_the_credentials_were_removed_when_the_ctf_had_them(self):
        self.assertEqual(
            with_credentials_note("Released.", stored_ctf(credentials_message_id=42)),
            "Released.\nCredentials message removed.",
        )

    def test_says_nothing_more_without_credentials(self):
        self.assertEqual(with_credentials_note("Released.", stored_ctf()), "Released.")


if __name__ == "__main__":
    unittest.main()
