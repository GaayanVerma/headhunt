"""Run async coroutines from CrewAI's synchronous tool/_run surface."""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import Awaitable, TypeVar

T = TypeVar("T")


def run_sync(coro: Awaitable[T]) -> T:
    """Execute an awaitable from sync code, even if an event loop is already running.

    CrewAI tools are sync. Our search backends (SerperClient, PeopleSearchScraper)
    are async. When no loop is running, asyncio.run is enough; when one is
    (nested callers, some CrewAI versions), run the coroutine in a worker thread
    with its own loop so we don't nest asyncio.run.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()
