import asyncio
import os
import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

import discord
from discord import app_commands

# GitPython refuses to be imported without a git executable; nothing here runs git
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

import cogs
from bot import Hector
from cogs import players
from core import checks, errors
from core.settings import Settings

GUILD_ID = 123
ENV = {
    "BOT_TOKEN": "token",
    "GUILD_ID": str(GUILD_ID),
    "ADMIN_ROLE": "sv{admin}",
    "MANAGER_ROLE": "sv{manager}",
    "MODERATOR_ROLE": "sv{moderator}",
}

COMMANDS = {
    "help",
    "setup-ctf",
    "add-player",
    "remove-player",
    "last-call",
    "release-ctf",
    "lock-ctf",
    "archive-ctf",
    "remove-ctf",
    "ctf-status",
    "add-category",
    "create-challenge",
    "solved",
    "unsolve",
    "archive-channel",
    "ctftime-check",
    "ctftime-table",
    "calendar-sync",
    "blog-check",
}
ALWAYS_SCHEDULED = {"ctf-timeline", "ctftime-check", "monthly-ctftime-table"}


async def started_bot(env=ENV):
    """The bot with every cog added, as it is before it logs in."""
    bot = Hector(Settings.from_env(env), cogs=cogs.ALL)
    await bot.add_cogs()
    return bot


class BotTest(unittest.IsolatedAsyncioTestCase):
    async def test_every_command_is_registered_for_the_server_only(self):
        bot = await started_bot()

        self.assertEqual({command.name for command in bot.tree.get_commands(guild=bot.home)}, COMMANDS)
        self.assertEqual(bot.tree.get_commands(), [])

    async def test_every_name_and_description_fits_discords_limits(self):
        # Discord refuses to sync the commands at startup when one doesn't fit
        bot = await started_bot()

        for command in bot.tree.get_commands(guild=bot.home):
            definition = command.to_dict(bot.tree)
            for item in [definition, *definition["options"]]:
                with self.subTest(command=command.name, item=item["name"]):
                    self.assertLessEqual(len(item["name"]), 32)
                    self.assertLessEqual(len(item["description"]), 100)

    async def test_failing_commands_get_the_error_reply(self):
        bot = await started_bot()

        self.assertIs(bot.tree.on_error, errors.on_app_command_error)

    async def test_feeds_without_settings_are_not_scheduled(self):
        bot = await started_bot()

        self.assertEqual({job.name for job in bot.scheduler.jobs}, ALWAYS_SCHEDULED)

    async def test_configured_feeds_are_scheduled(self):
        bot = await started_bot({**ENV, "ICS_URL": "https://example.com/cal.ics", "LEARNING_FORUM_ID": "42"})

        self.assertEqual({job.name for job in bot.scheduler.jobs}, ALWAYS_SCHEDULED | {"calendar-sync", "blog-check"})

    async def test_the_join_buttons_work_for_every_ctf(self):
        with mock.patch.object(Hector, "add_dynamic_items") as add_dynamic_items:
            await started_bot()

        add_dynamic_items.assert_called_once_with(players.JoinButton, players.LeaveButton, players.DecisionButton)


class FakeChannel:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    async def send(self, message, **kwargs):
        if self.fail is not None:
            raise self.fail
        self.sent.append(message)


class AlertTest(unittest.IsolatedAsyncioTestCase):
    """Alerts go to the CTF's #bot, else to the admin channel, else only to the log."""

    BOT_CHANNEL_ID, ADMIN_CHANNEL_ID = 10, 20

    def setUp(self):
        self.bot_channel, self.admin_channel = FakeChannel(), FakeChannel()
        self.ctf = SimpleNamespace(name="Foo CTF", bot_channel_id=self.BOT_CHANNEL_ID)

    def bot(self, admin_channel=True, bot_channel_gone=False):
        env = {**ENV, "ADMIN_CHANNEL_ID": str(self.ADMIN_CHANNEL_ID)} if admin_channel else ENV
        bot = Hector(Settings.from_env(env))

        async def channel(channel_id):
            if channel_id == self.BOT_CHANNEL_ID:
                if bot_channel_gone:
                    raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Channel")
                return self.bot_channel
            return self.admin_channel

        bot.channel = channel
        return bot

    async def test_a_ctf_alert_goes_to_its_bot_channel(self):
        await self.bot().alert_ctf(self.ctf, "hi")

        self.assertEqual((self.bot_channel.sent, self.admin_channel.sent), (["hi"], []))

    async def test_without_a_ctf_or_its_bot_channel_the_admins_are_alerted(self):
        await self.bot().alert_ctf(None, "no ctf")
        with self.assertLogs("bot", level="WARNING"):
            await self.bot(bot_channel_gone=True).alert_ctf(self.ctf, "bot gone")

        self.assertEqual(self.admin_channel.sent, ["no ctf", "bot gone"])

    async def test_without_an_admin_channel_the_alert_is_only_logged(self):
        with self.assertLogs("bot", level="WARNING") as logs:
            await self.bot(admin_channel=False).alert_admins("lost")

        self.assertIn("lost", logs.output[0])

    async def test_try_alert_admins_says_whether_it_was_posted(self):
        self.assertTrue(await self.bot().try_alert_admins("hi"))

        self.admin_channel.fail = RuntimeError("Discord is down")
        with self.assertLogs("bot", level="ERROR"):
            self.assertFalse(await self.bot().try_alert_admins("hi"))

    async def test_an_alert_gives_up_after_the_alert_timeout(self):
        bot = self.bot()

        async def hang(channel_id):
            await asyncio.sleep(10)

        bot.channel = hang
        with mock.patch("bot.ALERT_TIMEOUT", timedelta(milliseconds=10)), self.assertRaises(TimeoutError):
            await bot.alert_ctf(self.ctf, "hi")


class FakeResponse:
    def __init__(self, done=False):
        self.done, self.sent = done, []

    def is_done(self):
        return self.done

    async def send_message(self, content):
        self.sent.append(content)


def interaction(role_names=(), done=False):
    settings = Settings.from_env(ENV)
    followups = []

    async def followup_send(content):
        followups.append(content)

    return SimpleNamespace(
        client=SimpleNamespace(settings=settings),
        user=SimpleNamespace(roles=[SimpleNamespace(name=name) for name in role_names]),
        command=SimpleNamespace(name="setup-ctf"),
        response=FakeResponse(done),
        followup=SimpleNamespace(send=followup_send, sent=followups),
    )


class ChecksTest(unittest.IsolatedAsyncioTestCase):
    async def passes(self, check, role_names):
        predicate = check()(lambda: None).__discord_app_commands_checks__[0]
        try:
            return await predicate(interaction(role_names))
        except app_commands.MissingAnyRole:
            return False

    async def test_each_group_lets_in_its_roles_only(self):
        cases = [
            (checks.admins_only, "sv{admin}", "sv{manager}"),
            (checks.managers_only, "sv{manager}", "sv{moderator}"),
            (checks.staff_only, "sv{moderator}", "sv{player}"),
        ]
        for check, allowed, refused in cases:
            with self.subTest(check=check.__name__):
                self.assertTrue(await self.passes(check, [refused, allowed]))
                self.assertFalse(await self.passes(check, [refused]))


class ErrorHandlerTest(unittest.IsolatedAsyncioTestCase):
    async def test_a_missing_role_is_refused(self):
        failed = interaction()

        await errors.on_app_command_error(failed, app_commands.MissingAnyRole(["sv{admin}"]))

        self.assertEqual(failed.response.sent, [errors.NOT_ALLOWED])

    async def test_any_other_error_is_logged_and_apologized_for_also_after_deferring(self):
        failed = interaction(done=True)

        with self.assertLogs("bot", level="ERROR"):
            await errors.on_app_command_error(failed, app_commands.AppCommandError("boom"))

        self.assertEqual(failed.followup.sent, [errors.UNKNOWN_ERROR])


if __name__ == "__main__":
    unittest.main()
