"""Pronunciation evaluation API routes."""
# NOTE: no `from __future__ import annotations` — slowapi's wrapper breaks
# FastAPI's UploadFile forward-ref resolution when annotations are deferred.

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.dependencies import get_pronunciation_svc, verify_api_key
from app.api.middleware import limiter
from app.api.upload import evaluate_upload
from app.core.config import get_settings
from app.models.schemas import ErrorResponse, PronunciationResponse
from app.services.pronunciation_service import PronunciationService

router = APIRouter(prefix="/api/v1", tags=["pronunciation"])


def _evaluate_rate() -> str:
    return f"{get_settings().rate_limit_evaluate_per_minute}/minute"


@router.post(
    "/evaluate",
    response_model=PronunciationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        422: {"model": ErrorResponse, "description": "Reference text rejected"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal error"},
        503: {"model": ErrorResponse, "description": "Server busy (queue full)"},
        504: {"model": ErrorResponse, "description": "Request timeout"},
    },
    summary="Evaluate pronunciation",
    description=(
        "Upload an audio file and reference text. Returns IPA comparison, "
        "GOP scores, and overall pronunciation feedback. "
        "Requires a valid API key in the **X-API-Key** header."
    ),
)
@limiter.limit(_evaluate_rate)
async def evaluate_pronunciation(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (wav, mp3, ogg, flac)"),
    reference_text: str = Form(..., description="Reference text to compare against"),
    svc: PronunciationService = Depends(get_pronunciation_svc),
    _: None = Depends(verify_api_key),
) -> PronunciationResponse:
    """Evaluate pronunciation from an audio file against reference text."""
    return await evaluate_upload(audio, reference_text, svc.evaluate)
