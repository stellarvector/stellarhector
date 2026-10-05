import unittest

from ctf import store
from ctf.models import Category, Challenge, Player, PlayerStatus
from tests.factories import new_ctf, use_temporary_database, utc


class StoreTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)

    def test_created_ctf_is_found_by_name_with_all_its_details(self):
        created = store.create(new_ctf(ctftime_id=3352, start=utc(2026, 10, 10, 8), finish=utc(2026, 10, 12, 8)))

        found = store.find(name="Foo CTF")

        self.assertEqual(found, created)
        self.assertEqual(found.name, "Foo CTF")
        self.assertEqual(found.ctftime_id, 3352)
        self.assertEqual(found.start, utc(2026, 10, 10, 8))
        self.assertEqual(found.finish, utc(2026, 10, 12, 8))
        self.assertEqual(
            (found.role_id, found.category_id, found.main_channel_id, found.bot_channel_id, found.guide_message_id),
            (1, 2, 3, 4, 5),
        )

    def test_lifecycle_steps_are_not_done_yet(self):
        found = store.create(new_ctf())

        self.assertEqual(
            (
                found.last_call_at,
                found.released_at,
                found.locked_at,
                found.archived_at,
                found.removal_reminded_at,
                found.removed_at,
            ),
            (None,) * 6,
        )

    def test_name_is_found_ignoring_case(self):
        created = store.create(new_ctf())

        self.assertEqual(store.find(name="foo ctf"), created)

    def test_found_by_ctftime_id(self):
        created = store.create(new_ctf(ctftime_id=3352))

        self.assertEqual(store.find(ctftime_id=3352), created)

    def test_unknown_ctf_is_not_found(self):
        store.create(new_ctf(ctftime_id=3352))

        self.assertIsNone(store.find(name="Bar CTF"))
        self.assertIsNone(store.find(ctftime_id=1))

    def test_ctf_without_ctftime_id_is_not_found_by_a_missing_id(self):
        store.create(new_ctf())

        self.assertIsNone(store.find(ctftime_id=None))

    def test_removed_ctf_is_not_found_and_its_name_can_be_used_again(self):
        old = store.create(new_ctf(ctftime_id=3352))
        store.mark_removed(old.id, utc(2026, 11, 1))

        self.assertIsNone(store.find(name="Foo CTF"))
        self.assertIsNone(store.find(ctftime_id=3352))
        again = store.create(new_ctf(ctftime_id=3352))
        self.assertEqual(store.find(name="Foo CTF"), again)

    def test_found_by_category_id(self):
        created = store.create(new_ctf(category_id=2))

        self.assertEqual(store.find_by_category(2), created)
        self.assertIsNone(store.find_by_category(3))

    def test_removed_ctf_is_not_found_by_category(self):
        old = store.create(new_ctf(category_id=2))
        store.mark_removed(old.id, utc(2026, 11, 1))

        self.assertIsNone(store.find_by_category(2))

    def test_found_by_id_also_when_removed(self):
        created = store.create(new_ctf())
        store.mark_removed(created.id, utc(2026, 11, 1))

        self.assertEqual(store.get(created.id).removed_at, utc(2026, 11, 1))
        self.assertIsNone(store.get(created.id + 1))

    def test_managed_ctfs_are_those_not_removed_by_start_with_those_without_dates_last(self):
        manual = store.create(new_ctf(name="Manual CTF"))
        later = store.create(new_ctf(name="Later CTF", ctftime_id=2, start=utc(2026, 11, 1), finish=utc(2026, 11, 2)))
        sooner = store.create(new_ctf(name="Sooner CTF", ctftime_id=1, start=utc(2026, 10, 1), finish=utc(2026, 10, 2)))
        removed = store.create(new_ctf(name="Removed CTF"))
        store.mark_removed(removed.id, utc(2026, 10, 3))

        self.assertEqual(store.managed(), [sooner, later, manual])

    def test_has_no_join_message_until_it_is_stored(self):
        created = store.create(new_ctf())
        self.assertEqual((created.join_channel_id, created.join_message_id), (None, None))

        store.set_join_message(created.id, 6, 7)

        found = store.get(created.id)
        self.assertEqual((found.join_channel_id, found.join_message_id), (6, 7))

    def test_deleted_ctf_is_gone_with_its_players_categories_and_challenges_and_its_name_can_be_used_again(self):
        created = store.create(new_ctf())
        store.add_player(created.id, 42, utc(2026, 10, 3, 12))
        store.add_category(created.id, "web", 8)
        store.add_challenge(created.id, "web", "xss", 10)

        store.delete(created.id)

        self.assertIsNone(store.get(created.id))
        self.assertEqual(store.players(created.id), [])
        self.assertEqual(store.categories(created.id), [])
        self.assertIsNone(store.challenge(created.id, "web", "xss"))
        store.create(new_ctf())

    def test_has_no_overview_message_until_it_is_stored(self):
        created = store.create(new_ctf())
        self.assertIsNone(created.overview_message_id)

        store.set_overview_message(created.id, 77)

        self.assertEqual(store.get(created.id).overview_message_id, 77)

    def test_release_time_is_stored_once(self):
        created = store.create(new_ctf())

        self.assertTrue(store.mark_released(created.id, utc(2026, 10, 13, 8)))
        self.assertFalse(store.mark_released(created.id, utc(2026, 10, 14, 8)))

        self.assertEqual(store.get(created.id).released_at, utc(2026, 10, 13, 8))

    def test_lock_time_is_stored_once(self):
        created = store.create(new_ctf())

        self.assertTrue(store.mark_locked(created.id, utc(2026, 10, 17, 8)))
        self.assertFalse(store.mark_locked(created.id, utc(2026, 10, 18, 8)))

        self.assertEqual(store.get(created.id).locked_at, utc(2026, 10, 17, 8))

    def test_archive_time_is_stored(self):
        created = store.create(new_ctf())
        store.mark_archived(created.id, utc(2026, 10, 20, 9))

        self.assertEqual(store.find(name="Foo CTF").archived_at, utc(2026, 10, 20, 9))


class PlayersTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf())

    def test_added_player_is_joined(self):
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertEqual(
            store.players(self.ctf.id),
            [
                Player(
                    user_id=42,
                    status=PlayerStatus.JOINED,
                    approval_card_message_id=None,
                    joined_at=utc(2026, 10, 3, 12),
                )
            ],
        )

    def test_adding_a_player_again_keeps_one_entry_and_the_first_join_time(self):
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        store.add_player(self.ctf.id, 42, utc(2026, 10, 4, 12))

        self.assertEqual([(p.user_id, p.joined_at) for p in store.players(self.ctf.id)], [(42, utc(2026, 10, 3, 12))])

    def test_adding_a_pending_player_makes_them_joined_without_approval_card(self):
        store.add_pending_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        store.set_approval_card(self.ctf.id, 42, 77)

        store.add_player(self.ctf.id, 42, utc(2026, 10, 4, 12))

        self.assertEqual(
            store.players(self.ctf.id),
            [
                Player(
                    user_id=42,
                    status=PlayerStatus.JOINED,
                    approval_card_message_id=None,
                    joined_at=utc(2026, 10, 3, 12),
                )
            ],
        )

    def test_player_asking_to_join_is_pending_until_their_approval_card_is_posted(self):
        store.add_pending_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        self.assertEqual(
            store.player(self.ctf.id, 42),
            Player(
                user_id=42,
                status=PlayerStatus.PENDING,
                approval_card_message_id=None,
                joined_at=utc(2026, 10, 3, 12),
            ),
        )

        self.assertTrue(store.set_approval_card(self.ctf.id, 42, 77))

        self.assertEqual(store.player(self.ctf.id, 42).approval_card_message_id, 77)

    def test_approval_card_is_not_stored_for_who_no_longer_waits(self):
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertFalse(store.set_approval_card(self.ctf.id, 42, 77))
        self.assertFalse(store.set_approval_card(self.ctf.id, 43, 78))

        self.assertIsNone(store.player(self.ctf.id, 42).approval_card_message_id)

    def test_someone_not_on_the_list_is_no_player(self):
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertIsNone(store.player(self.ctf.id, 43))

    def test_removed_player_is_gone_and_other_players_stay(self):
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        store.add_player(self.ctf.id, 43, utc(2026, 10, 3, 13))

        store.remove_player(self.ctf.id, 42)
        store.remove_player(self.ctf.id, 99)

        self.assertEqual([p.user_id for p in store.players(self.ctf.id)], [43])

    def test_players_are_per_ctf(self):
        other = store.create(new_ctf(name="Bar CTF"))
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))

        self.assertEqual(store.players(other.id), [])

    def test_reopened_request_waits_on_its_card_again_whether_or_not_they_are_on_the_list(self):
        store.add_player(self.ctf.id, 42, utc(2026, 10, 4, 12))

        store.reopen_request(self.ctf.id, 42, utc(2026, 10, 3, 12), 77)
        store.reopen_request(self.ctf.id, 43, utc(2026, 10, 3, 13), 78)

        self.assertEqual(
            store.players(self.ctf.id),
            [
                Player(
                    user_id=42,
                    status=PlayerStatus.PENDING,
                    approval_card_message_id=77,
                    joined_at=utc(2026, 10, 3, 12),
                ),
                Player(
                    user_id=43,
                    status=PlayerStatus.PENDING,
                    approval_card_message_id=78,
                    joined_at=utc(2026, 10, 3, 13),
                ),
            ],
        )

    def test_times_joined_counts_the_ctfs_the_user_joined_not_those_they_wait_for(self):
        other, third = store.create(new_ctf(name="Bar CTF")), store.create(new_ctf(name="Baz CTF"))
        store.add_player(self.ctf.id, 42, utc(2026, 10, 3, 12))
        store.add_player(other.id, 42, utc(2026, 10, 3, 12))
        store.add_pending_player(third.id, 42, utc(2026, 10, 3, 12))
        store.add_player(third.id, 43, utc(2026, 10, 3, 12))

        self.assertEqual(store.times_joined(42), 2)
        self.assertEqual(store.times_joined(99), 0)


class CategoriesTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf())

    def test_categories_are_listed_by_slug(self):
        store.add_category(self.ctf.id, "web", 8)
        store.add_category(self.ctf.id, "crypto", 9)

        self.assertEqual(store.categories(self.ctf.id), [Category("crypto", 9), Category("web", 8)])

    def test_categories_are_per_ctf(self):
        other = store.create(new_ctf(name="Bar CTF"))
        store.add_category(self.ctf.id, "web", 8)
        store.add_category(other.id, "web", 9)

        self.assertEqual(store.categories(other.id), [Category("web", 9)])

    def test_storing_a_category_again_gives_it_the_new_channel(self):
        store.add_category(self.ctf.id, "web", 8)
        store.add_category(self.ctf.id, "web", 9)

        self.assertEqual(store.categories(self.ctf.id), [Category("web", 9)])

    def test_category_is_found_by_its_channel(self):
        store.add_category(self.ctf.id, "web", 8)
        other = store.create(new_ctf(name="Bar CTF"))
        store.add_category(other.id, "crypto", 9)

        self.assertEqual(store.category_by_channel(self.ctf.id, 8), Category("web", 8))
        self.assertIsNone(store.category_by_channel(self.ctf.id, 9))


class ChallengesTest(unittest.TestCase):
    def setUp(self):
        use_temporary_database(self)
        self.ctf = store.create(new_ctf())

    def test_a_stored_challenge_is_found_unsolved(self):
        store.add_challenge(self.ctf.id, "web", "xss", 10)

        self.assertEqual(store.challenge(self.ctf.id, "web", "xss"), Challenge("web", "xss", 10, solved=False))

    def test_challenges_are_per_category_and_ctf(self):
        other = store.create(new_ctf(name="Bar CTF"))
        store.add_challenge(self.ctf.id, "web", "xss", 10)

        self.assertIsNone(store.challenge(self.ctf.id, "pwn", "xss"))
        self.assertIsNone(store.challenge(other.id, "web", "xss"))

    def test_storing_a_challenge_again_gives_it_the_new_thread(self):
        store.add_challenge(self.ctf.id, "web", "xss", 10)
        store.add_challenge(self.ctf.id, "web", "xss", 11)

        self.assertEqual(store.challenge(self.ctf.id, "web", "xss").thread_id, 11)

    def test_challenges_are_listed_by_category_then_slug(self):
        other = store.create(new_ctf(name="Bar CTF"))
        store.add_challenge(self.ctf.id, "web", "xss", 10)
        store.add_challenge(self.ctf.id, "crypto", "rsa", 11)
        store.add_challenge(self.ctf.id, "web", "sqli", 12)
        store.add_challenge(other.id, "web", "csrf", 13)

        self.assertEqual(
            store.challenges(self.ctf.id),
            [
                Challenge("crypto", "rsa", 11, solved=False),
                Challenge("web", "sqli", 12, solved=False),
                Challenge("web", "xss", 10, solved=False),
            ],
        )

    def test_challenge_is_found_by_its_thread(self):
        store.add_challenge(self.ctf.id, "web", "xss", 10)
        other = store.create(new_ctf(name="Bar CTF"))
        store.add_challenge(other.id, "web", "csrf", 11)

        self.assertEqual(store.challenge_by_thread(self.ctf.id, 10), Challenge("web", "xss", 10, solved=False))
        self.assertIsNone(store.challenge_by_thread(self.ctf.id, 11))

    def test_marking_solved_changes_it_once(self):
        store.add_challenge(self.ctf.id, "web", "xss", 10)

        self.assertTrue(store.set_solved(self.ctf.id, "web", "xss", True))
        self.assertFalse(store.set_solved(self.ctf.id, "web", "xss", True))
        self.assertTrue(store.challenge(self.ctf.id, "web", "xss").solved)

    def test_marking_unsolved_changes_it_once(self):
        store.add_challenge(self.ctf.id, "web", "xss", 10)
        store.set_solved(self.ctf.id, "web", "xss", True)

        self.assertTrue(store.set_solved(self.ctf.id, "web", "xss", False))
        self.assertFalse(store.set_solved(self.ctf.id, "web", "xss", False))
        self.assertFalse(store.challenge(self.ctf.id, "web", "xss").solved)

    def test_storing_a_challenge_again_keeps_it_solved(self):
        store.add_challenge(self.ctf.id, "web", "xss", 10)
        store.set_solved(self.ctf.id, "web", "xss", True)
        store.add_challenge(self.ctf.id, "web", "xss", 11)

        self.assertTrue(store.challenge(self.ctf.id, "web", "xss").solved)


if __name__ == "__main__":
    unittest.main()
