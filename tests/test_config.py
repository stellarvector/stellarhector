import unittest
from datetime import timedelta
from core import config


class RoleNamesTest(unittest.TestCase):
    def test_returns_configured_names_in_order(self):
        values = {"ADMIN_ROLE": "sv{admin}", "MANAGER_ROLE": "sv{manager}"}

        self.assertEqual(config.role_names(values, "ADMIN_ROLE", "MANAGER_ROLE"), ["sv{admin}", "sv{manager}"])

    def test_skips_unset_and_blank_roles(self):
        values = {"ADMIN_ROLE": "sv{admin}", "MODERATOR_ROLE": "  "}

        self.assertEqual(config.role_names(values, "ADMIN_ROLE", "MANAGER_ROLE", "MODERATOR_ROLE"), ["sv{admin}"])


class ChannelIdTest(unittest.TestCase):
    def test_parses_the_id(self):
        self.assertEqual(config.channel_id({"ADMIN_CHANNEL_ID": "123456789012345678"}, "ADMIN_CHANNEL_ID"), 123456789012345678)

    def test_unset_is_none(self):
        self.assertIsNone(config.channel_id({}, "ADMIN_CHANNEL_ID"))

    def test_blank_is_none(self):
        self.assertIsNone(config.channel_id({"ADMIN_CHANNEL_ID": ""}, "ADMIN_CHANNEL_ID"))
        self.assertIsNone(config.channel_id({"ADMIN_CHANNEL_ID": None}, "ADMIN_CHANNEL_ID"))

    def test_invalid_is_none(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertIsNone(config.channel_id({"ADMIN_CHANNEL_ID": "#admin"}, "ADMIN_CHANNEL_ID"))


class TimezoneTest(unittest.TestCase):
    def test_defaults_to_brussels(self):
        self.assertEqual(config.timezone({}), "Europe/Brussels")
        self.assertEqual(config.timezone({"TIMEZONE": ""}), "Europe/Brussels")

    def test_uses_configured_zone(self):
        self.assertEqual(config.timezone({"TIMEZONE": "UTC"}), "UTC")

    def test_unknown_zone_falls_back_to_default(self):
        with self.assertLogs("bot", level="WARNING"):
            self.assertEqual(config.timezone({"TIMEZONE": "Europe/Brusels"}), "Europe/Brussels")


class WatchdogLimitTest(unittest.TestCase):
    DEFAULT = timedelta(minutes=20)
    TICK = timedelta(minutes=5)

    def limit(self, values):
        return config.watchdog_limit(values, self.DEFAULT, self.TICK)

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
        self.assertEqual(config.positive_int({}, "ICS_POLL_MINUTES", 15), 15)
        self.assertEqual(config.positive_int({"ICS_POLL_MINUTES": " "}, "ICS_POLL_MINUTES", 15), 15)

    def test_uses_configured_number(self):
        self.assertEqual(config.positive_int({"ICS_POLL_MINUTES": "30"}, "ICS_POLL_MINUTES", 15), 30)

    def test_invalid_or_zero_falls_back_to_default(self):
        for value in ["fifteen", "0", "-5", "1.5"]:
            with self.subTest(value=value), self.assertLogs("bot", level="WARNING"):
                self.assertEqual(config.positive_int({"ICS_POLL_MINUTES": value}, "ICS_POLL_MINUTES", 15), 15)
