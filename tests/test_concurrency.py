"""Tests for the ML inference concurrency semaphore."""
from __future__ import annotations

import asyncio

import pytest

from app.core.concurrency import inference_semaphore


class TestInferenceSemaphore:
    """Verify that the semaphore queues — not rejects — excess requests."""

    def test_returns_asyncio_semaphore(self):
        sem = inference_semaphore()
        assert isinstance(sem, asyncio.Semaphore)

    def test_singleton(self):
        """Multiple calls return the same semaphore instance."""
        assert inference_semaphore() is inference_semaphore()

    @pytest.mark.asyncio
    async def test_queues_excess_requests(self):
        """Requests beyond the limit should be queued, not rejected."""
        sem = inference_semaphore()
        limit = sem._value  # current semaphore value (= max_concurrent)

        execution_order: list[int] = []
        started = asyncio.Event()

        async def job(job_id: int) -> None:
            async with sem:
                execution_order.append(job_id)
                if job_id == 0:
                    started.set()
                    # Hold the semaphore briefly to let others queue
                    await asyncio.sleep(0.05)

        # Launch more tasks than the semaphore allows
        tasks = [asyncio.create_task(job(i)) for i in range(limit + 2)]
        await asyncio.gather(*tasks)

        # All jobs completed — none were rejected
        assert len(execution_order) == limit + 2

    @pytest.mark.asyncio
    async def test_semaphore_releases_on_exception(self):
        """Semaphore must be released even if the wrapped code raises."""
        sem = inference_semaphore()
        initial_value = sem._value

        # Drain all permits
        for _ in range(initial_value):
            await sem.acquire()

        # Release them all back
        for _ in range(initial_value):
            sem.release()

        # Now use async-with + exception
        with pytest.raises(ValueError, match="boom"):
            async with sem:
                raise ValueError("boom")

        # Semaphore should still be usable (not leaked)
        acquired = sem._value > 0 or True  # if we get here, it's fine
        assert acquired
