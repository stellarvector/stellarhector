import asyncio


class UnfinishedWork:
    """Work that goes on when the run doing it is stopped, such as posting something and remembering it was posted.
    The next run waits for it, so it does not do the same work again."""

    def __init__(self):
        self._tasks = set()

    async def wait(self):
        """Wait for the work of runs that were stopped while it ran."""
        if self._tasks:
            await asyncio.wait(self._tasks)

    async def finish_even_if_stopped(self, work):
        """Await the coroutine work, which goes on when the run is stopped meanwhile; wait waits for it."""
        task = asyncio.ensure_future(work)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return await asyncio.shield(task)
