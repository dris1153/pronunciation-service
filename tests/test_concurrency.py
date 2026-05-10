"""Tests for the ML inference concurrency semaphore (Phase 02)."""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from app.core.concurrency import (
    _detect_available_cpus,
    _semaphore,
    inference_semaphore,
)


class TestDetectCpus:
    def test_returns_at_least_one(self):
        assert _detect_available_cpus() >= 1

    def test_capped_at_max(self, monkeypatch):
        from app.core import concurrency
        # Force a huge affinity set → must still be capped at the constant.
        monkeypatch.setattr(
            concurrency.os, "sched_getaffinity",
            lambda _: set(range(64)), raising=False,
        )
        assert _detect_available_cpus() == concurrency.MAX_CONCURRENT_INFERENCES_CAP


@pytest.fixture(autouse=True)
def _fresh_semaphore():
    """Clear the lru_cache so each test gets a Semaphore bound to its own loop."""
    _semaphore.cache_clear()
    yield
    _semaphore.cache_clear()


class TestInferenceSemaphore:
    """Verify the context manager queues, then 503s on timeout."""

    @pytest.mark.asyncio
    async def test_singleton_within_loop(self):
        a = _semaphore()
        b = _semaphore()
        assert a is b
        assert isinstance(a, asyncio.Semaphore)

    @pytest.mark.asyncio
    async def test_queues_excess_requests(self):
        sem = _semaphore()
        limit = sem._value
        execution_order: list[int] = []

        async def job(job_id: int) -> None:
            async with inference_semaphore(timeout=10.0):
                execution_order.append(job_id)
                if job_id == 0:
                    await asyncio.sleep(0.05)

        tasks = [asyncio.create_task(job(i)) for i in range(limit + 2)]
        await asyncio.gather(*tasks)
        assert len(execution_order) == limit + 2

    @pytest.mark.asyncio
    async def test_queue_timeout_returns_503(self):
        sem = _semaphore()
        held = sem._value
        for _ in range(held):
            await sem.acquire()
        try:
            with pytest.raises(HTTPException) as exc:
                async with inference_semaphore(timeout=0.05):
                    pass
            assert exc.value.status_code == 503
            assert "Retry-After" in exc.value.headers
        finally:
            for _ in range(held):
                sem.release()

    @pytest.mark.asyncio
    async def test_releases_on_exception(self):
        sem = _semaphore()
        initial = sem._value
        with pytest.raises(ValueError, match="boom"):
            async with inference_semaphore(timeout=10.0):
                raise ValueError("boom")
        assert sem._value == initial
