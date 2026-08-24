"""Unit tests for crew async_utils and import gating."""

import pytest

from linkedin_scraper.crew.async_utils import run_sync


pytestmark = pytest.mark.unit


async def _add(a: int, b: int) -> int:
    return a + b


def test_run_sync_without_running_loop():
    assert run_sync(_add(2, 3)) == 5


@pytest.mark.asyncio
async def test_run_sync_inside_running_loop():
    # Nested: we're already in an event loop; run_sync must still return.
    assert run_sync(_add(4, 5)) == 9
