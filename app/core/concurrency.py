"""Concurrency guards for CPU-intensive ML inference.

Provides an ``asyncio.Semaphore`` that limits how many ML inference jobs can
run concurrently.  This prevents resource exhaustion (CPU/RAM) when multiple
requests arrive at the same time — requests beyond the limit are **queued**
(not rejected), so no work is lost.

Usage::

    from app.core.concurrency import inference_semaphore

    async def my_endpoint():
        async with inference_semaphore():
            result = await loop.run_in_executor(None, heavy_work)

The concurrency limit is controlled via ``MAX_CONCURRENT_INFERENCES`` in
``.env`` (default ``2``).
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

from loguru import logger


@lru_cache
def inference_semaphore() -> asyncio.Semaphore:
    """Return a singleton ``asyncio.Semaphore`` for ML inference throttling.

    The semaphore value is read from ``Settings.max_concurrent_inferences``
    once and cached.  Requests that exceed the limit are **queued** (they
    ``await`` the semaphore) rather than rejected, so the caller never gets
    an error — they just wait their turn.
    """
    from app.core.config import get_settings

    limit = get_settings().max_concurrent_inferences
    logger.info("ML inference concurrency limit: {}", limit)
    return asyncio.Semaphore(limit)
