import unittest
from utils.archive.naming import normalize_name, relative_link, unique_name


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


class UniqueNameTest(unittest.TestCase):
    def test_normalizes_the_name(self):
        self.assertEqual(unique_name("✅ sqli", set()), "sqli")

    def test_takes_the_name(self):
        taken = set()
        unique_name("sqli", taken)
        self.assertEqual(taken, {"sqli"})

    def test_numbers_a_name_that_is_taken(self):
        taken = {"sqli"}
        self.assertEqual(unique_name("✅ sqli", taken), "sqli-2")
        self.assertEqual(unique_name("sqli", taken), "sqli-3")

    def test_uses_the_fallback_when_nothing_remains(self):
        self.assertEqual(unique_name("🔥", set(), fallback="thread-42"), "thread-42")


class RelativeLinkTest(unittest.TestCase):
    def test_between_pages_in_the_same_folder(self):
        self.assertEqual(relative_link("web/sqli.html", "web/xss.html"), "xss.html")

    def test_down_into_a_folder(self):
        self.assertEqual(relative_link("foo-ctf.html", "web/sqli.html"), "web/sqli.html")

    def test_up_out_of_a_folder(self):
        self.assertEqual(relative_link("web/sqli.html", "foo-ctf.html"), "../foo-ctf.html")

    def test_across_folders(self):
        self.assertEqual(relative_link("web/sqli.html", "crypto/index.html"), "../crypto/index.html")

    def test_above_the_root(self):
        self.assertEqual(relative_link("web/sqli.html", "../index.html"), "../../index.html")
        self.assertEqual(relative_link("foo-ctf.html", "../index.html"), "../index.html")

    def test_far_above_the_root(self):
        self.assertEqual(relative_link("foo-ctf.html", "../../../common/archive.css"), "../../../common/archive.css")
        self.assertEqual(relative_link("web/sqli.html", "../../../common/archive.css"), "../../../../common/archive.css")


if __name__ == "__main__":
    unittest.main()
