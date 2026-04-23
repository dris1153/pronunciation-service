"""FastAPI application factory."""
from __future__ import annotations

from contextlib import asynccontextmanager
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle."""
    setup_logging()
    settings = get_settings()
    logger.info("Starting {} v{}", settings.app_name, settings.app_version)

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
