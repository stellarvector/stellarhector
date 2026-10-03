from utils.archive.category import CategoryArchive
from utils.archive.challenge import ChallengeArchive
from utils.archive.naming import normalize_name, relative_link, unique_name
from git import Repo
import asyncio
import datetime
import core.bot as bot
import os

# The folder of a CTF's archive (and of each category in it) has its attachments in this folder
ATTACHMENTS_FOLDER = "attachments"

class CtfArchive():
    """A CTF's archive: a page for its main channel, with its threads inline, and a folder per category channel with
    the category's page and a page per challenge thread (utils.archive.category)."""
    @classmethod
    async def init(cls, ctf, main_channel, category_channels):
        self = CtfArchive()

        # First sync archive repository
        _ = await CtfArchive.sync_repository()

        self.name = ctf
        self.year = datetime.datetime.now().year

        self.__main: ChallengeArchive | None = None
        if main_channel is not None:
            self.__main = await ChallengeArchive.init(main_channel)
            self.__main.path = f"{normalize_name(main_channel.name, fallback=f'channel-{main_channel.id}')}.html"

        taken = {ATTACHMENTS_FOLDER}
        self.__categories: list[CategoryArchive] = [
            await CategoryArchive.init(channel, unique_name(channel.name, taken, fallback=f"channel-{channel.id}"))
                for channel in category_channels
        ]

        return self

    def generate_files(self):
        archive_path = bot.config.get("ARCHIVE_LOCAL_PATH")

        pages = self.pages()
        if not pages:
            raise RuntimeError("The CTF has no channels to archive")

        self.add_year_if_necessary(archive_path)
        ctf_path = self.create_ctf_path(archive_path)

        if not ctf_path:
            raise RuntimeError("No CTF name could be found")

        self.add_ctf_to_year_index(archive_path, ctf_path, pages[0].path)

        ctf_folder = f"{self.year}/{ctf_path}"
        if self.__main is not None:
            self.write_page(archive_path, ctf_folder, self.__main, self.__main.fetch_data(
                self.attachment_folder(archive_path, ctf_folder)))

        for category in self.__categories:
            attachments = self.attachment_folder(archive_path, f"{ctf_folder}/{category.folder}")
            self.write_page(archive_path, ctf_folder, category, category.fetch_data(attachments))

            for challenge in category.challenges:
                self.write_page(archive_path, ctf_folder, challenge, challenge.fetch_data(attachments))

    def pages(self):
        """Every page of the archive, in the order of the navigation."""
        main = [] if self.__main is None else [self.__main]
        return main + [page for category in self.__categories for page in [category, *category.challenges]]

    @staticmethod
    def attachment_folder(archive_path, folder):
        """Create the attachments folder in the folder (relative to the archive) and return its path from the
        archive's root, which is where attachments are downloaded to."""
        os.makedirs(os.path.join(archive_path, folder, ATTACHMENTS_FOLDER), exist_ok=True)
        return f"/{folder}/{ATTACHMENTS_FOLDER}"

    def write_page(self, archive_path, ctf_folder, page, messages):
        def link(to_page):
            return relative_link(page.path, to_page)

        navigation = []
        if self.__main is not None:
            navigation.append({"name": self.__main.name, "link": link(self.__main.path), "challenges": []})
        navigation += [{
            "name": category.name,
            "link": link(category.path),
            "challenges": [{"name": challenge.name, "link": link(challenge.path)} for challenge in category.challenges],
        } for category in self.__categories]

        page_template = bot.jinja_env.get_template("ctf_page.html")
        page_html = page_template.render(
            year=self.year,
            ctf_name=self.name,
            page_name=page.name,
            # The common folder is next to the year folders
            stylesheet=link("../../common/archive.css"),
            codehilite_stylesheet=link("../../common/codehilite.css"),
            year_index=link("../index.html"),
            navigation=navigation,
            messages=messages)

        with open(os.path.join(archive_path, ctf_folder, page.path), "w+") as f:
            f.write(page_html)

    def add_year_if_necessary(self, archive_path):
        year_folder_path = os.path.join(archive_path, str(self.year))
        if os.path.exists(year_folder_path):
            return

        os.makedirs(f"{archive_path}/{self.year}")

        year_link_template = bot.jinja_env.get_template("yearlink.html")
        year_link_html = year_link_template.render(year=self.year)

        index_path = os.path.join(archive_path, "index.html")
        with open(index_path, "r+") as index_file:
            index_html = index_file.read()
            index_file.seek(0)
            index_html = index_html.replace("<!--add-year-->", year_link_html)
            index_file.write(index_html)

        year_template = bot.jinja_env.get_template("year.html")
        year_html = year_template.render(year=self.year)

        year_index_path = os.path.join(archive_path, str(self.year), "index.html")
        with open(year_index_path, "w+") as year_file:
            year_file.write(year_html)

    def create_ctf_path(self, archive_path):
        ctf_path = False

        for i in range(100):
            if os.path.exists(f"{archive_path}/{self.year}/{self.name}{'' if i == 0 else f'-{i}'}"):
                continue

            ctf_path = f"{self.name}" + ('' if i == 0 else f'-{i}')
            os.makedirs(f"{archive_path}/{self.year}/{ctf_path}")
            break

        return ctf_path

    def add_ctf_to_year_index(self, archive_path, ctf_path, first_page):
        ctf_link_template = bot.jinja_env.get_template("ctflink.html")
        ctf_link_html = ctf_link_template.render(ctf={"link": f"./{ctf_path}/{first_page}", "name": self.name})

        year_index_path = os.path.join(archive_path, str(self.year), "index.html")
        with open(year_index_path, "r+") as year_file:
            year_html = year_file.read()
            year_file.seek(0)
            year_html = year_html.replace("<!--add-ctf-->", ctf_link_html)
            year_file.write(year_html)

    async def save(self):
        await asyncio.to_thread(self._save)

    def _save(self):
        repository = CtfArchive.get_archive_repository()
        if int(bot.config.get("SHOULD_COMMIT")):
            repository = Repo(bot.config.get("ARCHIVE_LOCAL_PATH"))
            repository.index.add('*')
            repository.index.commit(f"Archive {self.name} {self.year}")

            if int(bot.config.get("SHOULD_PUSH")):
                origin = repository.remote(name="origin")
                origin.push()

    # git clone, pull and push can take a while; they run in a thread so the event loop
    # (and with it the scheduler heartbeat) keeps going
    @staticmethod
    async def sync_repository():
        return await asyncio.to_thread(CtfArchive.get_archive_repository)

    @staticmethod
    def get_archive_repository():
        if not os.path.exists(bot.config.get("ARCHIVE_LOCAL_PATH")):
            # Clone repository if not present locally
            repo = Repo.clone_from(bot.config.get("ARCHIVE_REMOTE_URL"), bot.config.get("ARCHIVE_LOCAL_PATH"))
            return repo
        else:
            # Pull potential changes from repository
            repo = Repo(bot.config.get("ARCHIVE_LOCAL_PATH"))
            repo.remotes.origin.pull()
            return repo
