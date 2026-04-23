"""Health-check route."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.models.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Health check")
async def health_check() -> HealthResponse:
    settings = get_settings()
    try:
        from app.services.asr_service import get_asr_service
        model_loaded = get_asr_service() is not None
    except Exception:
        model_loaded = False

    return HealthResponse(
        status="ok",
        version=settings.app_version,
        model_loaded=model_loaded,
    )
