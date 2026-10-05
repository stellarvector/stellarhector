import unittest
from types import SimpleNamespace

from cogs.challenges import added_reply, started_reply
from ctf.categories import Added
from ctf.challenges import Started
from ctf.models import Category


class ReportTest(unittest.TestCase):
    def test_lists_what_was_created_existed_and_was_skipped(self):
        added = Added(created=[SimpleNamespace(id=42)], existing=[Category("web", 7)], invalid=["🔥"])

        self.assertEqual(
            added_reply(added),
            f"Created <#{added.created[0].id}> :muscle:\n"
            "Already exists: <#7>\n"
            "Skipped `🔥`: a category name needs letters or digits",
        )

    def test_only_the_parts_that_apply(self):
        self.assertEqual(added_reply(Added(existing=[Category("web", 7)])), "Already exists: <#7>")

    def test_no_names(self):
        self.assertEqual(
            added_reply(Added()),
            "Give the category names, comma-separated: `/add-category web, crypto, pwn`",
        )


class ReplyTest(unittest.TestCase):
    def test_new_challenge_links_its_thread(self):
        thread = SimpleNamespace(mention="<#42>")

        self.assertEqual(
            started_reply(Started(thread, "xss", created=True)),
            f"Started {thread.mention}, go solve that thing :muscle:",
        )

    def test_existing_challenge_points_to_its_thread(self):
        thread = SimpleNamespace(mention="<#42>")

        self.assertEqual(
            started_reply(Started(thread, "xss", created=False)),
            f"`xss` already exists, you were added to {thread.mention}",
        )


if __name__ == "__main__":
    unittest.main()
