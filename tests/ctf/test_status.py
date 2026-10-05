import unittest
from datetime import timedelta

from ctf import status
from ctf.models import Player, PlayerStatus, Stage
from tests.factories import FINISH, LAST_CALL, LOCK, RELEASE, START, stored_ctf, utc

GUILD_ID = 99
NOW = utc(2026, 10, 8, 8)
JOINED_AT = utc(2026, 10, 1, 12)


def ts(moment):
    return int(moment.timestamp())


def players(joined, pending):
    return [Player(user_id, PlayerStatus.JOINED, None, JOINED_AT) for user_id in range(joined)] + [
        Player(100 + user_id, PlayerStatus.PENDING, 7, JOINED_AT) for user_id in range(pending)
    ]


class StageTest(unittest.TestCase):
    def test_a_ctf_is_set_up_until_it_is_released(self):
        self.assertEqual(stored_ctf(last_call_at=LAST_CALL).stage, Stage.SET_UP)

    def test_released(self):
        self.assertEqual(stored_ctf(released_at=RELEASE).stage, Stage.RELEASED)

    def test_locked_while_its_archive_failed(self):
        self.assertEqual(stored_ctf(released_at=RELEASE, locked_at=LOCK).stage, Stage.LOCKED)

    def test_archived(self):
        self.assertEqual(stored_ctf(released_at=RELEASE, locked_at=LOCK, archived_at=LOCK).stage, Stage.ARCHIVED)

    def test_archived_by_command_before_the_lock(self):
        self.assertEqual(stored_ctf(released_at=RELEASE, archived_at=LOCK).stage, Stage.ARCHIVED)

    def test_joining_closes_once_released(self):
        self.assertFalse(stored_ctf(last_call_at=LAST_CALL).joining_closed)
        self.assertTrue(stored_ctf(released_at=RELEASE).joining_closed)
        self.assertTrue(stored_ctf(archived_at=LOCK).joining_closed)


class LineTest(unittest.TestCase):
    def test_names_the_ctf_its_links_dates_stage_next_step_and_players(self):
        line = status.line(stored_ctf(), players(joined=3, pending=1), GUILD_ID, NOW)

        self.assertEqual(
            line,
            f"**[Foo CTF](https://discord.com/channels/99/3)** · "
            f"[CTFtime](<https://ctftime.org/event/3352/>) · <t:{ts(START)}:f> – <t:{ts(FINISH)}:f>"
            f" · set up · next: last call <t:{ts(LAST_CALL)}:R> · 3 joined, 1 pending",
        )

    def test_next_step_is_the_first_one_the_timeline_still_runs(self):
        line = status.line(stored_ctf(last_call_at=LAST_CALL), [], GUILD_ID, START)

        self.assertIn(f" · next: release <t:{ts(RELEASE)}:R> · ", line)

    def test_a_ctf_without_ctftime_id_is_manual_without_ctftime_link_or_dates(self):
        line = status.line(stored_ctf(ctftime_id=None, start=None, finish=None), [], GUILD_ID, NOW)

        self.assertEqual(
            line, "**[Foo CTF](https://discord.com/channels/99/3)** · set up · next: manual · 0 joined, 0 pending"
        )

    def test_a_ctf_with_ctftime_id_but_without_dates_is_manual(self):
        line = status.line(stored_ctf(start=None, finish=None), [], GUILD_ID, NOW)

        self.assertIn(" · set up · next: manual · ", line)

    def test_says_when_no_step_is_left(self):
        done = stored_ctf(
            last_call_at=LAST_CALL,
            released_at=RELEASE,
            locked_at=LOCK,
            archived_at=LOCK,
            removal_reminded_at=LOCK + timedelta(weeks=4),
        )

        self.assertIn(" · archived · next: nothing left · ", status.line(done, [], GUILD_ID, NOW))

    def test_markdown_in_the_name_does_not_break_the_link(self):
        line = status.line(stored_ctf(name="[Foo]_CTF"), [], GUILD_ID, NOW)

        self.assertTrue(line.startswith(r"**[(Foo)\_CTF](https://discord.com/channels/99/3)**"))


class ReportTest(unittest.TestCase):
    def test_says_so_when_no_ctf_is_managed(self):
        self.assertEqual(status.report([], GUILD_ID, NOW), ["No CTFs are managed by the bot right now."])

    def test_has_one_line_per_ctf_in_the_given_order(self):
        foo, bar = stored_ctf(), stored_ctf(name="Bar CTF", id=2)

        report = status.report([(foo, players(1, 0)), (bar, [])], GUILD_ID, NOW)

        self.assertEqual(
            report, ["\n".join([status.line(foo, players(1, 0), GUILD_ID, NOW), status.line(bar, [], GUILD_ID, NOW)])]
        )

    def test_is_split_over_messages_that_fit_the_limit_without_splitting_a_line(self):
        entries = [(stored_ctf(name=f"CTF {index}", id=index), []) for index in range(5)]
        lines = [status.line(stored, [], GUILD_ID, NOW) for stored, _ in entries]
        limit = len(lines[0]) * 2 + 1

        report = status.report(entries, GUILD_ID, NOW, limit=limit)

        self.assertEqual(report, ["\n".join(lines[0:2]), "\n".join(lines[2:4]), lines[4]])
