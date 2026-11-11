"""FastAPI application factory."""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from app.api.middleware import register_middleware
from app.api.routes import (
    health_router,
    ipa_router,
    model_info_router,
    pronunciation_router,
    transcribe_router,
)
from app.core.config import get_settings
from app.core.logging import setup_logging


# ── Worker count guard (Phase 02 / Finding 3) ───────────────────────────────
# Runs at module import time so multi-worker invocations crash before any
# 1.2 GB ASR model is loaded (would OOM the container).


def _detect_worker_count() -> int:
    sources: list[str | None] = [
        os.environ.get("WEB_CONCURRENCY"),
        os.environ.get("UVICORN_WORKERS"),
        os.environ.get("GUNICORN_WORKERS"),
    ]
    for flag in ("--workers", "-w"):
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            if idx + 1 < len(sys.argv):
                sources.append(sys.argv[idx + 1])
    counts = [int(s) for s in sources if s and s.isdigit()]
    return max(counts) if counts else 1


_worker_count = _detect_worker_count()
if _worker_count > 1:
    raise RuntimeError(
        f"Detected {_worker_count} workers but each loads ~1.2GB ASR model. "
        f"Run with a single worker (WEB_CONCURRENCY=1, no --workers/-w flag) "
        f"to avoid OOM. Sources checked: WEB_CONCURRENCY, UVICORN_WORKERS, "
        f"GUNICORN_WORKERS, sys.argv."
    )


def _verify_writable_dirs() -> None:
    """Verify /tmp (or TMPDIR) and the model cache dir are writable.

    Aborts startup loudly via :class:`RuntimeError` if not — better to crash
    early in container logs than fail at first request with a confusing
    PermissionError mid-inference.
    """
    settings = get_settings()
    candidates = [
        os.environ.get("TMPDIR", "/tmp"),
        settings.asr_model_cache_dir,
    ]
    for path in candidates:
        try:
            p = Path(path)
            p.mkdir(parents=True, exist_ok=True)
            test_file = p / f"_smoke_{os.getpid()}.tmp"
            test_file.write_bytes(b"x" * 1024)
            test_file.read_bytes()
            test_file.unlink()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Required directory {path!r} not writable: {exc}"
            ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    setup_logging()
    settings = get_settings()
    logger.info("Starting {} v{}", settings.app_name, settings.app_version)

    # Verify writable dirs before model load — surfaces non-root perm issues
    # immediately rather than mid-request.
    _verify_writable_dirs()

    # Must run before any torch parallel work (model load) — interop threads
    # can only be set once per process.
    import torch

    from app.core.concurrency import _resolve_concurrency, torch_threads_per_slot

    # Affinity can't see a CFS quota (docker --cpus, Railway): set
    # OMP_NUM_THREADS there and it wins over the computed value.
    if not os.environ.get("OMP_NUM_THREADS"):
        torch.set_num_threads(torch_threads_per_slot())
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        logger.warning("torch interop threads already initialised; left unchanged")
    logger.info(
        "Concurrent inference slots: {} | torch threads per slot: {}",
        _resolve_concurrency(),
        torch.get_num_threads(),
    )

    # Emit API key warning after logging is configured (not at import time)
    from app.api.dependencies import warn_if_api_key_disabled
    warn_if_api_key_disabled()

    # Pre-load heavy models so the first request isn't slow
    logger.info("Pre-loading ML models …")
    from app.services.asr_service import get_asr_service  # noqa: F811
    from app.services.gop_service import get_gop_service
    from app.services.ipa_service import get_ipa_service
    from app.services.prosody_service import get_prosody_service

    get_asr_service()
    get_ipa_service()
    get_gop_service()
    get_prosody_service()
    logger.info("All models loaded ✓")

    # Warn early if ffmpeg is missing — required for MP3/OGG/WebM decoding
    from app.utils.audio import _check_ffmpeg_available, _resolve_ffmpeg_path

    if not _check_ffmpeg_available():
        logger.warning(
            "ffmpeg not found. MP3, OGG, and WebM audio uploads will fail. "
            "Install: pip install imageio-ffmpeg  (or)  apt-get install ffmpeg"
        )
    else:
        logger.info("ffmpeg found: {}", _resolve_ffmpeg_path())

    yield  # ← application is running

    logger.info("Shutting down …")


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "REST API for evaluating English pronunciation quality. "
            "Provides IPA phoneme comparison and Goodness-of-Pronunciation (GOP) scoring."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    register_middleware(app)

    # Register routers
    app.include_router(health_router)
    app.include_router(pronunciation_router)
    app.include_router(ipa_router)
    app.include_router(transcribe_router)
    app.include_router(model_info_router)

    return app
