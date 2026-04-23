"""Model information API routes."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.constants import MAX_UPLOAD_MB, SUPPORTED_AUDIO_FORMATS
from app.models.schemas import ModelInfoResponse

router = APIRouter(prefix="/api/v1", tags=["info"])


@router.get(
    "/model-info",
    response_model=ModelInfoResponse,
    summary="Service and model information",
    description=(
        "Return metadata about the running service: ASR model, device, "
        "audio constraints, and supported formats. "
        "This endpoint is public — no API key required."
    ),
)
async def model_info() -> ModelInfoResponse:
    """Return service metadata and capabilities."""
    settings = get_settings()

    return ModelInfoResponse(
        app_name=settings.app_name,
        app_version=settings.app_version,
        asr_model=settings.asr_model_name,
        device=settings.device,
        sample_rate=settings.audio_sample_rate,
        max_duration_sec=settings.audio_max_duration_sec,
        max_upload_mb=MAX_UPLOAD_MB,
        supported_formats=SUPPORTED_AUDIO_FORMATS,
    )
