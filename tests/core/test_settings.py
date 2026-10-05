import unittest
from datetime import timedelta

from core import settings
from core.settings import Roles, Settings, SettingsError


class RolesTest(unittest.TestCase):
    ROLES = Roles(
        admin="sv{admin}",
        manager="sv{manager}",
        moderator="sv{moderator}",
        core_player="sv{core}",
        known_player="sv{known}",
        player="sv{player}",
        follower="sv{follower}",
    )

    def test_groups(self):
        self.assertEqual(self.ROLES.admins, {"sv{admin}"})
        self.assertEqual(self.ROLES.managers, {"sv{admin}", "sv{manager}"})
        self.assertEqual(self.ROLES.staff, {"sv{admin}", "sv{manager}", "sv{moderator}"})
        self.assertEqual(
            self.ROLES.trusted_players, {"sv{core}", "sv{known}", "sv{admin}", "sv{manager}", "sv{moderator}"}
        )

    def test_groups_skip_roles_that_are_not_configured(self):
        self.assertEqual(Roles(admin="sv{admin}").staff, {"sv{admin}"})
        self.assertEqual(Roles().managers, frozenset())


class ChannelIdTest(unittest.TestCase):
    def test_parses_the_id(self):
        self.assertEqual(
            settings.channel_id({"ADMIN_CHANNEL_ID": "123456789012345678"}, "ADMIN_CHANNEL_ID"), 123456789012345678
        )

    def test_unset_is_none(self):
        self.assertIsNone(settings.channel_id({}, "ADMIN_CHANNEL_ID"))

    def test_blank_is_none(self):
        self.assertIsNone(settings.channel_id({"ADMIN_CHANNEL_ID": ""}, "ADMIN_CHANNEL_ID"))
        self.assertIsNone(settings.channel_id({"ADMIN_CHANNEL_ID": None}, "ADMIN_CHANNEL_ID"))

    def test_invalid_is_none(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertIsNone(settings.channel_id({"ADMIN_CHANNEL_ID": "#admin"}, "ADMIN_CHANNEL_ID"))


class TimezoneTest(unittest.TestCase):
    def test_defaults_to_brussels(self):
        self.assertEqual(settings.timezone({}), "Europe/Brussels")
        self.assertEqual(settings.timezone({"TIMEZONE": ""}), "Europe/Brussels")

    def test_uses_configured_zone(self):
        self.assertEqual(settings.timezone({"TIMEZONE": "UTC"}), "UTC")

    def test_unknown_zone_falls_back_to_default(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(settings.timezone({"TIMEZONE": "Europe/Brusels"}), "Europe/Brussels")


class WatchdogLimitTest(unittest.TestCase):
    DEFAULT = timedelta(minutes=20)
    TICK = timedelta(minutes=5)

    def limit(self, values):
        return settings.watchdog_limit(values, self.DEFAULT, self.TICK)

    def test_defaults_when_unset(self):
        self.assertEqual(self.limit({}), self.DEFAULT)
        self.assertEqual(self.limit({"WATCHDOG_TIMEOUT_MINUTES": ""}), self.DEFAULT)

    def test_uses_configured_minutes(self):
        self.assertEqual(self.limit({"WATCHDOG_TIMEOUT_MINUTES": "6"}), timedelta(minutes=6))

    def test_not_a_number_falls_back_to_default(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(self.limit({"WATCHDOG_TIMEOUT_MINUTES": "twenty"}), self.DEFAULT)

    def test_not_longer_than_a_tick_falls_back_to_default(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(self.limit({"WATCHDOG_TIMEOUT_MINUTES": "5"}), self.DEFAULT)


class PositiveIntTest(unittest.TestCase):
    def test_defaults_when_unset(self):
        self.assertEqual(settings.positive_int({}, "ICS_POLL_MINUTES", 15), 15)
        self.assertEqual(settings.positive_int({"ICS_POLL_MINUTES": " "}, "ICS_POLL_MINUTES", 15), 15)

    def test_uses_configured_number(self):
        self.assertEqual(settings.positive_int({"ICS_POLL_MINUTES": "30"}, "ICS_POLL_MINUTES", 15), 30)

    def test_invalid_or_zero_falls_back_to_default(self):
        for value in ["fifteen", "0", "-5", "1.5"]:
            with self.subTest(value=value), self.assertLogs("bot", level="WARNING"):
                self.assertEqual(settings.positive_int({"ICS_POLL_MINUTES": value}, "ICS_POLL_MINUTES", 15), 15)


class FlagTest(unittest.TestCase):
    def test_on(self):
        for value in ["1", "2", "true", "Yes"]:
            with self.subTest(value=value):
                self.assertTrue(settings.flag({"SHOULD_PUSH": value}, "SHOULD_PUSH"))

    def test_off_when_unset_or_off(self):
        self.assertFalse(settings.flag({}, "SHOULD_PUSH"))
        self.assertFalse(settings.flag({"SHOULD_PUSH": "0"}, "SHOULD_PUSH"))

    def test_anything_else_is_off_with_a_warning(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertFalse(settings.flag({"SHOULD_PUSH": "maybe"}, "SHOULD_PUSH"))


class ColorTest(unittest.TestCase):
    def test_parses_hex_with_or_without_prefix(self):
        self.assertEqual(settings.color({"C": "0x00ff00"}, "C", 0), 0x00FF00)
        self.assertEqual(settings.color({"C": "ff0000"}, "C", 0), 0xFF0000)

    def test_defaults_when_unset(self):
        self.assertEqual(settings.color({}, "C", 0x123456), 0x123456)

    def test_invalid_falls_back_to_default(self):
        for value in ["green", "0x1000000"]:
            with self.subTest(value=value), self.assertLogs("bot", level="WARNING"):
                self.assertEqual(settings.color({"C": value}, "C", 0x123456), 0x123456)


class FromEnvTest(unittest.TestCase):
    REQUIRED = {"BOT_TOKEN": "token", "GUILD_ID": "123"}

    def test_reads_every_section(self):
        loaded = Settings.from_env(
            {
                **self.REQUIRED,
                "ADMIN_ROLE": "sv{admin}",
                "ADMIN_CHANNEL_ID": "42",
                "ARCHIVE_LOCAL_PATH": "/archive",
                "SHOULD_COMMIT": "1",
                "ICS_URL": "https://example.com/cal.ics",
                "ICS_LOOKAHEAD_DAYS": "7",
                "TIMEZONE": "UTC",
                "CTF_ROLE_COLOR_HEX": "0xff0000",
            }
        )

        self.assertEqual((loaded.bot_token, loaded.guild_id), ("token", 123))
        self.assertEqual(loaded.roles.admin, "sv{admin}")
        self.assertIsNone(loaded.roles.manager)
        self.assertEqual(loaded.channels.admin, 42)
        self.assertIsNone(loaded.channels.calendar)
        self.assertEqual(str(loaded.archive.local_path), "/archive")
        self.assertTrue(loaded.archive.commit)
        self.assertFalse(loaded.archive.push)
        self.assertEqual(loaded.calendar.ics_url, "https://example.com/cal.ics")
        self.assertEqual(loaded.calendar.lookahead, timedelta(days=7))
        self.assertEqual(loaded.timezone, "UTC")
        self.assertEqual(loaded.ctf_role_color, 0xFF0000)

    def test_optional_settings_have_defaults(self):
        loaded = Settings.from_env(self.REQUIRED)

        self.assertIsNone(loaded.calendar.ics_url)
        self.assertEqual(loaded.calendar.poll_minutes, 15)
        self.assertEqual(loaded.database_path, "./data/stellarhector.db")
        self.assertEqual(loaded.watchdog_limit, timedelta(minutes=20))
        self.assertIsNone(loaded.log_file)

    def test_bot_token_and_guild_id_are_required(self):
        for missing in self.REQUIRED:
            with self.subTest(missing=missing), self.assertRaises(SettingsError):
                Settings.from_env({key: value for key, value in self.REQUIRED.items() if key != missing})

    def test_switched_off_channels_are_warned_about(self):
        with self.assertLogs("bot", level="WARNING") as logs:
            Settings.from_env({**self.REQUIRED, "ADMIN_CHANNEL_ID": "42"}).warn_switched_off()

        self.assertEqual(len(logs.records), 4)
        self.assertNotIn("ADMIN_CHANNEL_ID", "".join(logs.output))
