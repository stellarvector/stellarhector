import unittest

from feeds.calendar.description import plain_text


class PlainTextTest(unittest.TestCase):
    def test_plain_text_is_left_alone(self):
        for text in ("", "Bring snacks, please", "Line one\n\nLine two", "a < b and c > d", "Use <name> as login"):
            with self.subTest(text):
                self.assertEqual(plain_text(text), text)

    def test_google_calendar_link_after_line_breaks(self):
        link = "https://ctftime.org/event/2345"
        self.assertEqual(plain_text(f'Bring a laptop<br><br><a href="{link}">{link}</a>'), f"Bring a laptop\n\n{link}")

    def test_description_that_is_only_a_link(self):
        link = "https://ctftime.org/event/2345/"
        self.assertEqual(plain_text(f'<br><br><a href="{link}">{link}</a>'), link)

    def test_link_text_without_scheme_or_slash_is_the_url(self):
        self.assertEqual(
            plain_text('<a href="https://ctftime.org/event/2345/">ctftime.org/event/2345</a>'),
            "https://ctftime.org/event/2345/",
        )

    def test_link_with_other_text_keeps_both(self):
        self.assertEqual(
            plain_text('See <a href="https://ctftime.org/event/2345">the CTF</a>.'),
            "See the CTF (https://ctftime.org/event/2345).",
        )

    def test_link_through_google_is_unwrapped(self):
        self.assertEqual(
            plain_text(
                '<a href="https://www.google.com/url?q=https://ctftime.org/event/2345&amp;sa=D">'
                "https://ctftime.org/event/2345</a>"
            ),
            "https://ctftime.org/event/2345",
        )

    def test_html_with_tag_like_text_drops_only_the_tags(self):
        self.assertEqual(plain_text("Pizza<br>Use <name> as login"), "Pizza\nUse as login")

    def test_formatting_is_dropped_and_entities_decoded(self):
        self.assertEqual(plain_text("<b>Pizza</b> &amp; <i>drinks</i>&nbsp;provided"), "Pizza & drinks provided")

    def test_paragraphs_and_lists_become_lines(self):
        self.assertEqual(
            plain_text("<p>Bring:</p><ul><li>a laptop</li><li>snacks</li></ul><p>See you!</p>"),
            "Bring:\n\n- a laptop\n- snacks\n\nSee you!",
        )

    def test_whitespace_in_the_html_is_no_line_break(self):
        self.assertEqual(plain_text("One\n  two<br>three"), "One two\nthree")


if __name__ == "__main__":
    unittest.main()
