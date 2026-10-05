"""The git repository that the archives are committed to. Clone, pull and push can take a while, so they run in a
thread to keep the event loop (and with it the scheduler heartbeat) running."""

import asyncio
from pathlib import Path

from git import Repo

from core.settings import ArchiveSettings


class Repository:
    def __init__(self, settings: ArchiveSettings) -> None:
        self.settings = settings
        # Held by an archive from its sync to its save, so two archives never edit the indexes or commit at once
        self.lock = asyncio.Lock()

    @property
    def path(self) -> Path:
        return self.settings.local_path

    async def sync(self) -> None:
        """Clone the repository if it is not checked out yet, otherwise pull, so archives build on the latest
        version."""
        await asyncio.to_thread(self._sync)

    async def save(self, message: str, paths: list[str]) -> None:
        """Commit `paths` (relative to the repository, deletions included) and push, as far as the settings allow. If
        the commit or the push fails, the commit is undone and the files are kept."""
        await asyncio.to_thread(self._save, message, paths)

    def _sync(self) -> None:
        if not self.path.exists():
            if self.settings.remote_url is None:
                raise RuntimeError("ARCHIVE_REMOTE_URL is not set, so the archive repository can't be cloned")
            Repo.clone_from(self.settings.remote_url, self.path)
        else:
            Repo(self.path).remotes.origin.pull()

    def _save(self, message: str, paths: list[str]) -> None:
        if not self.settings.commit:
            return

        repository = Repo(self.path)
        try:
            repository.git.add("--all", *paths)
            repository.index.commit(message)
        except BaseException:
            # Leave nothing staged behind
            repository.head.reset(index=True, working_tree=False)
            raise

        if self.settings.push:
            try:
                # push() only reports a rejected push; it does not raise
                repository.remote(name="origin").push().raise_if_error()
            except BaseException:
                # Undo the commit but keep the files
                repository.head.reset("HEAD~1", index=True, working_tree=False)
                raise
