"""The HTML archive of a CTF, written into the archive repository's checkout."""

import shutil
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Self, cast
from zoneinfo import ZoneInfo

import discord

from archive.category import CategoryArchive, ChallengeThreadArchive
from archive.message import PageItem
from archive.naming import first_free, normalize_name, relative_link, unique_name
from archive.page import ChannelPage
from archive.render import fill_marker, render

# The name of the attachments folder in a CTF's archive folder and in each category folder
ATTACHMENTS_FOLDER = "attachments"

Page = ChannelPage | CategoryArchive | ChallengeThreadArchive


class CtfArchive:
    """A CTF's archive in <root>/<year>/<name>: a page for its main channel (None when the channel is gone) with its
    threads inline, and a CategoryArchive for each category channel."""

    def __init__(
        self, name: str, root: Path, year: int, main: ChannelPage | None, categories: list[CategoryArchive]
    ) -> None:
        self.name = name
        self.root = root
        self.year = year
        self.main = main
        self.categories = categories
        # What generate_files changed, so discard_files can undo it: the folders it made, and the original content
        # of the files it edited
        self._made_folders: list[Path] = []
        self._edited_files: dict[Path, str] = {}

    @classmethod
    async def load(
        cls,
        name: str,
        main_channel: discord.TextChannel | None,
        category_channels: Iterable[discord.TextChannel],
        root: Path,
        year: int,
        zone: ZoneInfo,
    ) -> Self:
        main = None
        if main_channel is not None:
            path = f"{normalize_name(main_channel.name, fallback=f'channel-{main_channel.id}')}.html"
            main = await ChannelPage.load(main_channel, path, zone)

        taken = {ATTACHMENTS_FOLDER}
        categories = [
            await CategoryArchive.load(
                channel, unique_name(channel.name, taken, fallback=f"channel-{channel.id}"), zone
            )
            for channel in category_channels
        ]
        return cls(name, Path(root), year, main, categories)

    def pages(self) -> list[Page]:
        """Return every page of the archive, in navigation order."""
        main: list[Page] = [] if self.main is None else [self.main]
        pages = main
        for category in self.categories:
            pages.append(category)
            pages.extend(category.challenges)
        return pages

    def generate_files(self) -> None:
        """Write the archive's pages and attachments, and link the archive from the year's index, creating the year if
        needed. This blocks while attachments download, so run it off the event loop."""
        pages = self.pages()
        if not pages:
            raise RuntimeError("The CTF has no channels to archive")

        self._add_year_if_necessary()
        ctf_folder = self._make_ctf_folder()

        if self.main is not None:
            items = self.main.download_and_list_items(self._attachment_folder(ctf_folder))
            self._write_page(ctf_folder, self.main, items)

        for category in self.categories:
            attachments = self._attachment_folder(ctf_folder / category.folder)
            self._write_page(ctf_folder, category, category.download_and_list_items(attachments))
            for challenge in category.challenges:
                self._write_page(ctf_folder, challenge, challenge.download_and_list_items(attachments))

        # Done last, so the index never links to a CTF whose pages failed
        self._add_ctf_to_year_index(ctf_folder.name, cast(str, pages[0].path))

    def discard_files(self) -> None:
        """Undo generate_files, even if it failed halfway: remove the folders it made and restore the indexes it
        edited, so a retry starts from a clean state."""
        for path, content in self._edited_files.items():
            path.write_text(content)
        for folder in reversed(self._made_folders):
            shutil.rmtree(folder, ignore_errors=True)
        self._made_folders, self._edited_files = [], {}

    @property
    def _year_folder(self) -> Path:
        return self.root / str(self.year)

    @staticmethod
    def _attachment_folder(folder: Path) -> Path:
        attachments = folder / ATTACHMENTS_FOLDER
        attachments.mkdir(parents=True, exist_ok=True)
        return attachments

    def _write_page(self, ctf_folder: Path, page: Page, items: Sequence[PageItem]) -> None:
        # Every page in a CTF's archive has a path; only a channel's archive leaves it out
        page_path = cast(str, page.path)

        def link(to_page: str) -> str:
            return relative_link(page_path, to_page)

        navigation: list[dict[str, object]] = []
        if self.main is not None:
            navigation.append({"name": self.main.name, "link": link(cast(str, self.main.path)), "challenges": []})
        navigation += [
            {
                "name": category.name,
                "link": link(category.path),
                "challenges": [
                    {"name": challenge.name, "link": link(challenge.path)} for challenge in category.challenges
                ],
            }
            for category in self.categories
        ]

        html = render(
            "ctf_page.html",
            year=self.year,
            ctf_name=self.name,
            page_name=page.name,
            # The common folder sits next to the year folders
            stylesheet=link("../../common/archive.css"),
            codehilite_stylesheet=link("../../common/codehilite.css"),
            year_index=link("../index.html"),
            navigation=navigation,
            messages=items,
        )
        (ctf_folder / page_path).write_text(html)

    def _add_year_if_necessary(self) -> None:
        if self._year_folder.exists():
            return

        self._year_folder.mkdir(parents=True)
        self._made_folders.append(self._year_folder)

        index = self.root / "index.html"
        before = fill_marker(index, "<!--add-year-->", render("yearlink.html", year=self.year))
        self._edited_files.setdefault(index, before)
        (self._year_folder / "index.html").write_text(render("year.html", year=self.year))

    def _make_ctf_folder(self) -> Path:
        """Make the CTF's folder in the year folder. If an older archive already has that name, number the new one
        (-2, -3, ...) and leave the old one untouched."""
        base = normalize_name(self.name, fallback="ctf")
        folder = self._year_folder / first_free(base, lambda name: (self._year_folder / name).exists())
        folder.mkdir()
        self._made_folders.append(folder)
        return folder

    def _add_ctf_to_year_index(self, folder_name: str, first_page: str) -> None:
        index = self._year_folder / "index.html"
        link = render("ctflink.html", ctf={"link": f"./{folder_name}/{first_page}", "name": self.name})
        before = fill_marker(index, "<!--add-ctf-->", link)
        self._edited_files.setdefault(index, before)
