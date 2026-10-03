import unittest
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
