"""Concurrency guards for CPU-intensive ML inference.

Provides an :class:`asyncio.Semaphore` that limits how many ML inference jobs
run concurrently. Requests beyond the limit are queued; if the queue wait
exceeds :data:`Settings.inference_queue_timeout_sec`, callers receive an
HTTP 503 with ``Retry-After`` (Phase 02 / Finding 2 + queue-timeout).

CPU-detection respects cgroup quotas via :func:`os.sched_getaffinity` so
multi-tenant containers do not over-allocate (Finding 2).
"""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import HTTPException
from loguru import logger

from app.core.constants import MAX_CONCURRENT_INFERENCES_CAP


def _detect_available_cpus() -> int:
    """Return a safe inference concurrency count for the current container.

    ``sched_getaffinity`` honours cgroup CPU pinning on Linux. Falls back to
    ``cpu_count()`` on platforms without affinity support (macOS, Windows).
    Result is capped at :data:`MAX_CONCURRENT_INFERENCES_CAP` and at least 1.
    """
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        affinity = os.cpu_count() or 1
    # Leave one core for the event loop / OS scheduler.
    return max(1, min(affinity - 1, MAX_CONCURRENT_INFERENCES_CAP))


def _resolve_concurrency() -> int:
    from app.core.config import get_settings

    override = get_settings().max_concurrent_inferences
    return override if override > 0 else _detect_available_cpus()


@lru_cache
def _semaphore() -> asyncio.Semaphore:
    """Singleton semaphore — created lazily on first acquisition."""
    n = _resolve_concurrency()
    logger.info("ML inference concurrency limit: {}", n)
    return asyncio.Semaphore(n)


@asynccontextmanager
async def inference_semaphore(timeout: float | None = None):
    """Async context manager: acquire a slot or 503 after queue timeout.

    Parameters
    ----------
    timeout:
        Seconds to wait for a slot before raising HTTP 503. ``None`` reads
        the timeout from settings (default 60s).
    """
    if timeout is None:
        from app.core.config import get_settings

        timeout = get_settings().inference_queue_timeout_sec

    sem = _semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=503,
            detail="Server busy. Please retry shortly.",
            headers={"Retry-After": "30"},
        )
    try:
        yield
    finally:
        sem.release()
