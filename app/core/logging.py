"""Logging configuration using loguru.

Phase 05 / Finding 8 — single JSON-line records in prod for log aggregator
ingestion; human-readable colorised text in dev. Toggled via ``DEBUG`` —
no separate ``LOG_FORMAT`` env var.
"""
from __future__ import annotations

import sys

from loguru import logger

from app.core.config import get_settings


def setup_logging() -> None:
    """Configure application-wide logging."""
    settings = get_settings()

    logger.remove()  # remove default handler
    if settings.debug:
        logger.add(
            sys.stderr,
            level=settings.log_level,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
                "<level>{message}</level>"
            ),
            colorize=True,
        )
    else:
        # serialize=True emits one JSON line per record. Bound `extra` fields
        # (request_id, latency_ms, ...) attached via `logger.bind(...)` appear
        # under record["extra"].
        logger.add(sys.stdout, level=settings.log_level, serialize=True)

    logger.info("Logging configured — level={}  json={}", settings.log_level, not settings.debug)
