"""Pronunciation evaluation API routes, v2 (phone CTC model + learned scorer)."""
# NOTE: no `from __future__ import annotations` — see pronunciation.py (slowapi + UploadFile).

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api.dependencies import get_pronunciation_v2_svc, verify_api_key
from app.api.middleware import limiter
from app.api.routes.pronunciation import _evaluate_rate
from app.api.upload import evaluate_upload
from app.models.schemas import ErrorResponse, PronunciationResponseV2
from app.services.v2.pronunciation_v2_service import PronunciationV2Service

router = APIRouter(prefix="/api/v2", tags=["pronunciation-v2"])


@router.post(
    "/evaluate",
    response_model=PronunciationResponseV2,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        422: {"model": ErrorResponse, "description": "Reference text rejected"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal error"},
        503: {"model": ErrorResponse, "description": "Server busy or v2 model unavailable"},
        504: {"model": ErrorResponse, "description": "Request timeout"},
    },
    summary="Evaluate pronunciation (v2)",
    description=(
        "Same request and response shape as v1, scored by a phoneme-level model and a learned scorer, "
        "with per-word start_ms/end_ms. `transcribed_text` is the heard IPA string. "
        "Requires a valid API key in the **X-API-Key** header."
    ),
)
@limiter.limit(_evaluate_rate)
async def evaluate_pronunciation_v2(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (wav, mp3, ogg, flac)"),
    reference_text: str = Form(..., description="Reference text to compare against"),
    svc: PronunciationV2Service = Depends(get_pronunciation_v2_svc),
    _: None = Depends(verify_api_key),
) -> PronunciationResponseV2:
    return await evaluate_upload(audio, reference_text, svc.evaluate)
