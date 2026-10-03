import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from core import db
from utils import ctfs


def utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


def new_ctf(name="Foo CTF", ctftime_id=None, start=None, finish=None, role_id=1, category_id=2, main_channel_id=3,
            bot_channel_id=4, guide_message_id=5):
    return ctfs.NewCtf(name=name, ctftime_id=ctftime_id, start=start, finish=finish, role_id=role_id,
                       category_id=category_id, main_channel_id=main_channel_id, bot_channel_id=bot_channel_id,
                       guide_message_id=guide_message_id)


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)

    def test_created_ctf_is_found_by_name_with_all_its_details(self):
        created = ctfs.create(new_ctf(ctftime_id=3352, start=utc(2026, 10, 10, 8), finish=utc(2026, 10, 12, 8)))

        found = ctfs.find(name="Foo CTF")

        self.assertEqual(found, created)
        self.assertEqual(found.name, "Foo CTF")
        self.assertEqual(found.ctftime_id, 3352)
        self.assertEqual(found.start, utc(2026, 10, 10, 8))
        self.assertEqual(found.finish, utc(2026, 10, 12, 8))
        self.assertEqual((found.role_id, found.category_id, found.main_channel_id, found.bot_channel_id,
                          found.guide_message_id), (1, 2, 3, 4, 5))

    def test_lifecycle_steps_are_not_done_yet(self):
        found = ctfs.create(new_ctf())

        self.assertEqual((found.last_call_at, found.released_at, found.locked_at, found.archived_at,
                          found.removal_reminded_at, found.removed_at), (None,) * 6)

    def test_name_is_found_ignoring_case(self):
        created = ctfs.create(new_ctf())

        self.assertEqual(ctfs.find(name="foo ctf"), created)

    def test_found_by_ctftime_id(self):
        created = ctfs.create(new_ctf(ctftime_id=3352))

        self.assertEqual(ctfs.find(ctftime_id=3352), created)

    def test_unknown_ctf_is_not_found(self):
        ctfs.create(new_ctf(ctftime_id=3352))

        self.assertIsNone(ctfs.find(name="Bar CTF"))
        self.assertIsNone(ctfs.find(ctftime_id=1))

    def test_ctf_without_ctftime_id_is_not_found_by_a_missing_id(self):
        ctfs.create(new_ctf())

        self.assertIsNone(ctfs.find(ctftime_id=None))

    def test_removed_ctf_is_not_found_and_its_name_can_be_used_again(self):
        old = ctfs.create(new_ctf(ctftime_id=3352))
        ctfs.mark_removed(old.id, utc(2026, 11, 1))

        self.assertIsNone(ctfs.find(name="Foo CTF"))
        self.assertIsNone(ctfs.find(ctftime_id=3352))
        again = ctfs.create(new_ctf(ctftime_id=3352))
        self.assertEqual(ctfs.find(name="Foo CTF"), again)

    def test_found_by_category_id(self):
        created = ctfs.create(new_ctf(category_id=2))

        self.assertEqual(ctfs.find_by_category(2), created)
        self.assertIsNone(ctfs.find_by_category(3))

    def test_removed_ctf_is_not_found_by_category(self):
        old = ctfs.create(new_ctf(category_id=2))
        ctfs.mark_removed(old.id, utc(2026, 11, 1))

        self.assertIsNone(ctfs.find_by_category(2))

    def test_found_by_id_also_when_removed(self):
        created = ctfs.create(new_ctf())
        ctfs.mark_removed(created.id, utc(2026, 11, 1))

        self.assertEqual(ctfs.get(created.id).removed_at, utc(2026, 11, 1))
        self.assertIsNone(ctfs.get(created.id + 1))

    def test_has_no_join_message_until_it_is_stored(self):
        created = ctfs.create(new_ctf())
        self.assertEqual((created.join_channel_id, created.join_message_id), (None, None))

        ctfs.set_join_message(created.id, 6, 7)

        found = ctfs.get(created.id)
        self.assertEqual((found.join_channel_id, found.join_message_id), (6, 7))

    def test_deleted_ctf_is_gone_with_its_players_and_its_name_can_be_used_again(self):
        created = ctfs.create(new_ctf())
        ctfs.add_player(created.id, 42, utc(2026, 10, 3, 12))

        ctfs.delete(created.id)

        self.assertIsNone(ctfs.get(created.id))
        self.assertEqual(ctfs.players(created.id), [])
        ctfs.create(new_ctf())

    def test_archive_time_is_stored(self):
        created = ctfs.create(new_ctf())
        ctfs.mark_archived(created.id, utc(2026, 10, 20, 9))

        self.assertEqual(ctfs.find(name="Foo CTF").archived_at, utc(2026, 10, 20, 9))


class PlayersTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        db.init(Path(tmp.name) / "test.db")
        self.addCleanup(db.close)
        self.ctf = ctfs.create(new_ctf())

    def test_added_player_is_joined(self):
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertEqual(ctfs.players(self.ctf.id), [ctfs.Player(user_id=42, status="joined",
                                                                  approval_card_message_id=None,
                                                                  joined_at=utc(2026, 10, 3, 12))])

    def test_adding_a_player_again_keeps_one_entry_and_the_first_join_time(self):
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 4, 12))

        self.assertEqual([(p.user_id, p.joined_at) for p in ctfs.players(self.ctf.id)], [(42, utc(2026, 10, 3, 12))])

    def test_adding_a_pending_player_makes_them_joined_without_approval_card(self):
        ctfs.add_pending_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        ctfs.set_approval_card(self.ctf.id, 42, 77)

        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 4, 12))

        self.assertEqual(ctfs.players(self.ctf.id), [ctfs.Player(user_id=42, status="joined",
                                                                  approval_card_message_id=None,
                                                                  joined_at=utc(2026, 10, 3, 12))])

    def test_player_asking_to_join_is_pending_until_their_approval_card_is_posted(self):
        ctfs.add_pending_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        self.assertEqual(ctfs.player(self.ctf.id, 42), ctfs.Player(user_id=42, status="pending",
                                                                   approval_card_message_id=None,
                                                                   joined_at=utc(2026, 10, 3, 12)))

        ctfs.set_approval_card(self.ctf.id, 42, 77)

        self.assertEqual(ctfs.player(self.ctf.id, 42).approval_card_message_id, 77)

    def test_someone_not_on_the_list_is_no_player(self):
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertIsNone(ctfs.player(self.ctf.id, 43))

    def test_removed_player_is_gone_and_other_players_stay(self):
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        ctfs.add_player(self.ctf.id, 43, utc(2026, 10, 3, 13))

        ctfs.remove_player(self.ctf.id, 42)
        ctfs.remove_player(self.ctf.id, 99)

        self.assertEqual([p.user_id for p in ctfs.players(self.ctf.id)], [43])

    def test_players_are_per_ctf(self):
        other = ctfs.create(new_ctf(name="Bar CTF"))
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertEqual(ctfs.players(other.id), [])

    def test_reopened_request_waits_on_its_card_again_whether_or_not_they_are_on_the_list(self):
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 4, 12))

        ctfs.reopen_request(self.ctf.id, 42, utc(2026, 10, 3, 12), 77)
        ctfs.reopen_request(self.ctf.id, 43, utc(2026, 10, 3, 13), 78)

        self.assertEqual(ctfs.players(self.ctf.id), [
            ctfs.Player(user_id=42, status="pending", approval_card_message_id=77, joined_at=utc(2026, 10, 3, 12)),
            ctfs.Player(user_id=43, status="pending", approval_card_message_id=78, joined_at=utc(2026, 10, 3, 13))])

    def test_times_joined_counts_the_ctfs_the_user_joined_not_those_they_wait_for(self):
        other, third = ctfs.create(new_ctf(name="Bar CTF")), ctfs.create(new_ctf(name="Baz CTF"))
        ctfs.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        ctfs.add_player(other.id, 42, utc(2026, 10, 3, 12))
        ctfs.add_pending_player(third.id, 42, utc(2026, 10, 3, 12))
        ctfs.add_player(third.id, 43, utc(2026, 10, 3, 12))

        self.assertEqual(ctfs.times_joined(42), 2)
        self.assertEqual(ctfs.times_joined(99), 0)


if __name__ == "__main__":
    unittest.main()
