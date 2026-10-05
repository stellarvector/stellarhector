"""The refusals of the slash commands: run in the wrong place, on a locked CTF, or by someone not playing it. They
answer before doing any work, only to the user."""

import os
import unittest
from types import SimpleNamespace

# GitPython refuses to be imported without a git executable; nothing here runs git
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

from cogs.challenges import NOT_IN_CATEGORY, NOT_IN_CHALLENGE, NOT_PLAYING, Challenges
from cogs.ctf_lifecycle import CtfLifecycle
from cogs.replies import LOCKED
from core.settings import Settings
from ctf import store
from tests.factories import new_ctf, use_temporary_database, utc
from tests.fakes import LocatedChannel, LocatedThread

ROLE_ID, CATEGORY_ID, MAIN_ID, BOT_ID = 1, 2, 3, 4
SETTINGS = Settings.from_env({"BOT_TOKEN": "token", "GUILD_ID": "123", "ADMIN_ROLE": "sv{admin}"})


class FakeResponse:
    """What the command answered, as (content, ephemeral), and whether it deferred."""

    def __init__(self):
        self.sent, self.deferred = [], False

    async def send_message(self, content=None, ephemeral=False, **kwargs):
        self.sent.append((content, ephemeral))

    async def defer(self, **kwargs):
        self.deferred = True


class FakeMember:
    def __init__(self, *role_names, role_ids=()):
        self.roles = [SimpleNamespace(id=None, name=name) for name in role_names]
        self.roles += [SimpleNamespace(id=role_id, name="⚡ Foo CTF") for role_id in role_ids]

    def get_role(self, role_id):
        return next((role for role in self.roles if role.id == role_id), None)


def interaction(channel, user=None):
    return SimpleNamespace(channel=channel, user=user or FakeMember(), response=FakeResponse(), guild=None)


class CogTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        use_temporary_database(self)

        self.ctf = store.create(
            new_ctf(role_id=ROLE_ID, category_id=CATEGORY_ID, main_channel_id=MAIN_ID, bot_channel_id=BOT_ID)
        )
        self.main = LocatedChannel(CATEGORY_ID, channel_id=MAIN_ID)
        self.bot_channel = LocatedChannel(CATEGORY_ID, channel_id=BOT_ID)
        self.web = LocatedChannel(CATEGORY_ID)
        store.add_category(self.ctf.id, "web", self.web.id)
        self.thread = LocatedThread(self.web)
        store.add_challenge(self.ctf.id, "web", "sqli", self.thread.id)

        bot = SimpleNamespace(settings=SETTINGS)
        self.challenges, self.ctfs = Challenges(bot), CtfLifecycle(bot)
        self.player = FakeMember(role_ids=[ROLE_ID])

    def lock(self):
        store.mark_locked(self.ctf.id, utc(2026, 10, 1))

    async def run_command(self, cog, command, interaction, *args):
        await command.callback(cog, interaction, *args)
        self.assertFalse(interaction.response.deferred, "a refused command does no work")
        return interaction.response.sent

    def assert_refused(self, sent, content):
        self.assertEqual(sent, [(content, True)])


class AddCategoryTest(CogTest):
    async def test_only_in_the_main_channel(self):
        sent = await self.run_command(
            self.challenges, self.challenges.add_category_command, interaction(self.web), "pwn"
        )

        self.assert_refused(sent, f":no_entry: Run this in the main channel of the CTF: <#{MAIN_ID}>")

    async def test_not_on_a_locked_ctf(self):
        self.lock()

        sent = await self.run_command(
            self.challenges, self.challenges.add_category_command, interaction(self.main, self.player), "pwn"
        )

        self.assert_refused(sent, f":no_entry: {LOCKED}")

    async def test_not_by_who_does_not_play(self):
        sent = await self.run_command(
            self.challenges,
            self.challenges.add_category_command,
            interaction(self.main, FakeMember("sv{player}")),
            "pwn",
        )

        self.assert_refused(sent, NOT_PLAYING.format("add a category"))


class CreateChallengeTest(CogTest):
    async def test_only_in_a_category_channel_or_challenge_thread(self):
        sent = await self.run_command(
            self.challenges, self.challenges.create_challenge_command, interaction(self.main, self.player), "xss"
        )

        self.assert_refused(sent, f":no_entry: {NOT_IN_CATEGORY}")

    async def test_not_on_a_locked_ctf(self):
        self.lock()

        sent = await self.run_command(
            self.challenges, self.challenges.create_challenge_command, interaction(self.web, self.player), "xss"
        )

        self.assert_refused(sent, f":no_entry: {LOCKED}")

    async def test_staff_may_add_a_challenge_without_playing(self):
        sent = await self.run_command(
            self.challenges,
            self.challenges.create_challenge_command,
            interaction(self.web, FakeMember("sv{player}")),
            "xss",
        )
        self.assert_refused(sent, NOT_PLAYING.format("add a challenge"))

        admin = interaction(self.web, FakeMember("sv{admin}"))
        await self.run_command(self.challenges, self.challenges.create_challenge_command, admin, "!!!")
        self.assert_refused(admin.response.sent, ":no_entry: A challenge name needs letters or digits.")


class SolvedTest(CogTest):
    async def test_only_in_a_challenge_thread(self):
        sent = await self.run_command(
            self.challenges, self.challenges.solved_command, interaction(self.web, self.player), "flag{x}"
        )

        self.assert_refused(sent, f":no_entry: {NOT_IN_CHALLENGE}")

    async def test_not_on_a_locked_ctf(self):
        self.lock()

        sent = await self.run_command(
            self.challenges, self.challenges.solved_command, interaction(self.thread, self.player), "flag{x}"
        )

        self.assert_refused(sent, f":no_entry: {LOCKED}")

    async def test_only_by_its_players_not_even_staff(self):
        sent = await self.run_command(
            self.challenges,
            self.challenges.solved_command,
            interaction(self.thread, FakeMember("sv{admin}")),
            "flag{x}",
        )

        self.assert_refused(sent, NOT_PLAYING.format("mark a challenge solved"))

    async def test_unsolve_is_refused_on_a_locked_ctf_too(self):
        self.lock()

        sent = await self.run_command(
            self.challenges, self.challenges.unsolve_command, interaction(self.thread, FakeMember("sv{admin}"))
        )

        self.assert_refused(sent, f":no_entry: {LOCKED}")


class CtfsTest(CogTest):
    async def test_ctf_commands_run_only_in_its_bot_channel(self):
        for command in [
            self.ctfs.last_call_command,
            self.ctfs.release_ctf_command,
            self.ctfs.lock_ctf_command,
            self.ctfs.archive_ctf_command,
        ]:
            with self.subTest(command=command.name):
                sent = await self.run_command(self.ctfs, command, interaction(self.main))

                self.assert_refused(sent, f":no_entry: Run this in the #bot channel of the CTF: <#{BOT_ID}>")

    async def test_outside_any_ctf_it_says_to_run_it_in_a_ctf(self):
        sent = await self.run_command(self.ctfs, self.ctfs.release_ctf_command, interaction(LocatedChannel(None)))

        self.assert_refused(sent, ":no_entry: Run this in the #bot channel of a CTF")

    async def test_remove_ctf_refuses_a_ctf_that_was_never_archived(self):
        sent = await self.run_command(self.ctfs, self.ctfs.remove_ctf_command, interaction(self.bot_channel), False)

        self.assertEqual(len(sent), 1)
        self.assertIn("never archived", sent[0][0])


if __name__ == "__main__":
    unittest.main()
