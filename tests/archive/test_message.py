import unittest
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord

from archive.message import MessageArchive
from tests.factories import utc
from tests.fakes import fake_message

ZONE = ZoneInfo("Europe/Brussels")


def archived(text, **changes):
    message = fake_message(text)
    for key, value in changes.items():
        setattr(message, key, value)
    return MessageArchive(message, ZONE)


def attachment(id, filename):
    return SimpleNamespace(id=id, filename=filename, url=f"https://cdn.example.com/{filename}")


class MessageArchiveTest(unittest.TestCase):
    def test_markdown_becomes_html(self):
        body = archived("**bold** and `code`\nnext line").safe_body()

        self.assertIn("<strong>bold</strong>", body)
        self.assertIn("<code>code</code>", body)
        self.assertIn("<br", body)

    def test_html_in_a_message_is_sanitized(self):
        body = archived('<script>alert(1)</script><img src=x onerror="alert(2)">').safe_body()

        self.assertNotIn("<script", body)
        self.assertNotIn("onerror", body)

    def test_emoji_aliases_are_shown_as_emoji(self):
        self.assertIn("🚩", archived("got it :triangular_flag_on_post:").safe_body())

    def test_a_tenor_link_is_shown_as_its_gif(self):
        self.assertIn('src="https://tenor.com/view/cat.gif"', archived("https://tenor.com/view/cat").safe_body())

    def test_a_system_message_shows_discords_text_in_italics(self):
        body = archived("", system_content="alice pinned a message").safe_body()

        self.assertIn("<em>alice pinned a message</em>", body)

    def test_images_are_shown_and_other_attachments_linked(self):
        body = archived("", attachments=[attachment(1, "shot.PNG"), attachment(2, "chall.zip")]).safe_body()

        self.assertIn('<img alt="shot.PNG" src="./attachments/1_shot.PNG"', body)
        self.assertIn('<a href="./attachments/2_chall.zip"', body)

    def test_times_are_shown_in_the_zone(self):
        message = archived("hi", created_at=utc(2026, 7, 1, 10), edited_at=utc(2026, 7, 1, 11, 30))

        self.assertEqual(message.timestamp(), "2026-07-01 12:00:00")
        self.assertEqual(message.edit_timestamp(), "2026-07-01 13:30:00")

    def test_a_message_never_edited_has_no_edit_time(self):
        self.assertIsNone(archived("hi").edit_timestamp())

    def test_the_id_is_the_messages(self):
        message = archived("hi")

        self.assertEqual(message.id, message.original.id)
        self.assertEqual(message.original.type, discord.MessageType.default)


if __name__ == "__main__":
    unittest.main()
