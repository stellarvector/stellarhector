"""The archive repository against real git: a bare repository stands in for the remote."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

# Without git these tests are skipped; GitPython must not refuse to be imported then
os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")

from git.exc import GitCommandError

from archive.repository import Repository
from core.settings import ArchiveSettings


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class RepositoryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        # Commits are made by whoever runs the tests, with a name and email of its own
        for key, value in {
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@example.com",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@example.com",
        }.items():
            os.environ[key] = value
            self.addCleanup(os.environ.pop, key)

        self.remote = self.tmp / "remote.git"
        git("init", "--bare", "-b", "main", str(self.remote), cwd=self.tmp)
        self.other = self.clone("other")
        (self.other / "index.html").write_text("<ul><!--add-year--></ul>")
        self.commit_and_push(self.other, "Start the archive")

        self.local = self.tmp / "archive"

    def clone(self, name):
        git("clone", str(self.remote), name, cwd=self.tmp)
        return self.tmp / name

    def commit_and_push(self, checkout, message):
        git("add", "--all", cwd=checkout)
        git("commit", "-m", message, cwd=checkout)
        git("push", "origin", "HEAD:main", cwd=checkout)

    def repository(self, commit=True, push=True):
        return Repository(ArchiveSettings(local_path=self.local, remote_url=str(self.remote), commit=commit, push=push))

    def remote_log(self):
        return git("log", "--format=%s", "main", cwd=self.remote).splitlines()

    async def test_sync_clones_the_archive_then_pulls_it(self):
        repository = self.repository()

        await repository.sync()
        self.assertTrue((self.local / "index.html").exists())

        (self.other / "2026").mkdir()
        (self.other / "2026" / "index.html").write_text("2026")
        self.commit_and_push(self.other, "Add 2026")
        await repository.sync()

        self.assertEqual((self.local / "2026" / "index.html").read_text(), "2026")

    async def test_save_commits_only_the_given_paths_and_pushes(self):
        repository = self.repository()
        await repository.sync()
        (self.local / "2026").mkdir()
        (self.local / "2026" / "page.html").write_text("page")
        (self.local / "stray.txt").write_text("not part of this archive")

        await repository.save("Archive Foo 2026", ["2026", "index.html"])

        self.assertEqual(self.remote_log(), ["Archive Foo 2026", "Start the archive"])
        self.assertEqual(
            git("ls-tree", "-r", "--name-only", "main", cwd=self.remote).splitlines(), ["2026/page.html", "index.html"]
        )

    async def test_save_includes_deleted_files(self):
        repository = self.repository()
        await repository.sync()
        (self.local / "index.html").unlink()

        await repository.save("Remove the index", ["index.html"])

        self.assertEqual(git("ls-tree", "-r", "--name-only", "main", cwd=self.remote), "")

    async def test_without_commit_nothing_is_committed(self):
        repository = self.repository(commit=False)
        await repository.sync()
        (self.local / "page.html").write_text("page")

        await repository.save("Archive", ["page.html"])

        self.assertEqual(git("log", "--format=%s", cwd=self.local).splitlines(), ["Start the archive"])

    async def test_without_push_the_commit_stays_local(self):
        repository = self.repository(push=False)
        await repository.sync()
        (self.local / "page.html").write_text("page")

        await repository.save("Archive", ["page.html"])

        self.assertEqual(git("log", "-1", "--format=%s", cwd=self.local), "Archive")
        self.assertEqual(self.remote_log(), ["Start the archive"])

    async def test_a_rejected_push_raises_and_undoes_the_commit_keeping_the_files(self):
        repository = self.repository()
        await repository.sync()
        # Someone else pushed meanwhile, so the archive's push is not a fast-forward
        (self.other / "theirs.html").write_text("theirs")
        self.commit_and_push(self.other, "Their archive")
        (self.local / "page.html").write_text("page")

        with self.assertRaises(GitCommandError):
            await repository.save("Archive", ["page.html"])

        self.assertEqual(git("log", "--format=%s", cwd=self.local).splitlines(), ["Start the archive"])
        self.assertEqual(git("diff", "--cached", "--name-only", cwd=self.local), "")
        self.assertEqual((self.local / "page.html").read_text(), "page")
        self.assertEqual(self.remote_log(), ["Their archive", "Start the archive"])


if __name__ == "__main__":
    unittest.main()
