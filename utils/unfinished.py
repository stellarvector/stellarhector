import asyncio
from collections.abc import Awaitable
from typing import TypeVar, cast

T = TypeVar("T")


class UnfinishedWork:
    """Work that goes on when the run doing it is stopped, such as posting something and recording that it was posted.
    The next run waits for it, so it doesn't do the same work again."""

    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[object]] = set()

    async def wait(self) -> None:
        if self._tasks:
            await asyncio.wait(self._tasks)

    async def finish_even_if_stopped(self, work: Awaitable[T]) -> T:
        # The shield lets `work` go on when the run is cancelled; wait() waits for it
        task = asyncio.ensure_future(work)
        self._tasks.add(cast(asyncio.Task[object], task))
        task.add_done_callback(self._tasks.discard)
        return await asyncio.shield(task)
