import unittest
from utils.archive.naming import normalize_name


class NormalizeNameTest(unittest.TestCase):
    def test_keeps_alphanumerics_and_dashes(self):
        self.assertEqual(normalize_name("general-chat-2"), "general-chat-2")

    def test_removes_emoji(self):
        self.assertEqual(normalize_name("📚-study-group"), "study-group")

    def test_removes_special_characters(self):
        self.assertEqual(normalize_name("q&a_(old)!"), "qaold")

    def test_removes_non_ascii_letters(self):
        self.assertEqual(normalize_name("café"), "caf")

    def test_whitespace_becomes_dash(self):
        self.assertEqual(normalize_name("💬 General Stuff"), "General-Stuff")

    def test_collapses_repeated_dashes(self):
        self.assertEqual(normalize_name("a--b-🔥-c"), "a-b-c")

    def test_strips_leading_and_trailing_dashes(self):
        self.assertEqual(normalize_name("-🔥hot🔥-"), "hot")

    def test_falls_back_when_nothing_remains(self):
        self.assertEqual(normalize_name("🔥🔥", fallback="channel-42"), "channel-42")

    def test_default_fallback(self):
        self.assertEqual(normalize_name("🔥🔥"), "unnamed")


if __name__ == "__main__":
    unittest.main()
