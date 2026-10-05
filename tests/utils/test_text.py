import unittest

from utils.text import cut, inline_code


class CutTest(unittest.TestCase):
    def test_text_that_fits_is_kept(self):
        self.assertEqual(cut("abc", 3), "abc")

    def test_longer_text_is_cut_with_an_ellipsis_within_the_limit(self):
        self.assertEqual(cut("abcdef", 4), "abc…")


class InlineCodeTest(unittest.TestCase):
    def test_backticks_become_quotes(self):
        self.assertEqual(inline_code("bad `line`", 100), "`bad 'line'`")

    def test_text_is_cut_to_the_limit(self):
        self.assertEqual(inline_code("x" * 10, 4), "`xxxx`")


if __name__ == "__main__":
    unittest.main()
