from utils.archive.challenge import ChallengeArchive
from git import Repo
import datetime
import core.bot as bot
import os

class CtfArchive():
    @classmethod
    async def init(cls, ctf, challenges):
        self = CtfArchive()

        # First sync archive repository
        _ = self.get_archive_repository()

        self.name = ctf
        self.year = datetime.datetime.now().year
        self.__challenges: list[ChallengeArchive] = [
            await ChallengeArchive.init(channel)
                for channel in challenges
        ]

        return self

    def generate_files(self):
        archive_path = bot.config.get("ARCHIVE_LOCAL_PATH")

        self.add_year_if_necessary(archive_path)
        ctf_path = self.create_ctf_path(archive_path)

        if not ctf_path:
            raise RuntimeException("No CTF name could be found")

        self.add_ctf_to_year_index(archive_path, ctf_path)

        os.makedirs(f"{archive_path}/{self.year}/{ctf_path}/attachments")

        for challenge in self.__challenges:
            challenge_data = challenge.fetch_data(f"/{self.year}/{ctf_path}/attachments")

            challenge_template = bot.jinja_env.get_template("challenge.html")
            challenge_html = challenge_template.render(
                year=self.year,
                ctf_name=self.name,
                challenge_name=challenge.name,
                challenges=self.__challenges,
                messages=challenge_data)

            with open(f"{archive_path}/{self.year}/{ctf_path}/{challenge.name}.html", "w+") as f:
                f.write(challenge_html)

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

    def add_ctf_to_year_index(self, archive_path, ctf_path):
        ctf_link_template = bot.jinja_env.get_template("ctflink.html")
        ctf_link_html = ctf_link_template.render(ctf={"link": f"./{ctf_path}/{self.__challenges[0].name}.html", "name": self.name})

        year_index_path = os.path.join(archive_path, str(self.year), "index.html")
        with open(year_index_path, "r+") as year_file:
            year_html = year_file.read()
            year_file.seek(0)
            year_html = year_html.replace("<!--add-ctf-->", ctf_link_html)
            year_file.write(year_html)

    def save(self):
        repository = CtfArchive.get_archive_repository()
        if int(bot.config.get("SHOULD_COMMIT")):
            repository = Repo(bot.config.get("ARCHIVE_LOCAL_PATH"))
            repository.index.add('*')
            repository.index.commit(f"Archive {self.name} {self.year}")

            if int(bot.config.get("SHOULD_PUSH")):
                origin = repository.remote(name="origin")
                origin.push()

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
