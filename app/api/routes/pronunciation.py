"""Pronunciation evaluation API routes."""
# NOTE: no `from __future__ import annotations` — slowapi's wrapper breaks
# FastAPI's UploadFile forward-ref resolution when annotations are deferred.

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from loguru import logger

from app.api.dependencies import get_pronunciation_svc, verify_api_key
from app.api.middleware import limiter
from app.core.config import get_settings
from app.core.constants import ALLOWED_AUDIO_TYPES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from app.models.schemas import ErrorResponse, PronunciationResponse
from app.services.pronunciation_service import PronunciationService
from app.utils.audio import detect_audio_mime_type, precheck_audio_duration
from app.utils.text import validate_reference_text

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

    if not reference_text.strip():
        raise HTTPException(status_code=400, detail="reference_text must not be empty.")

    try:
        reference_text = validate_reference_text(reference_text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        audio_bytes = await audio.read()
        if len(audio_bytes) == 0:
            raise HTTPException(status_code=400, detail="Audio file is empty.")
        if len(audio_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Audio file too large "
                    f"({len(audio_bytes) / 1024 / 1024:.1f} MB). "
                    f"Maximum allowed size is {MAX_UPLOAD_MB} MB."
                ),
            )

        # Validate content type.  When the client omits the Content-Type header
        # (empty string), fall back to magic-bytes detection so that the check
        # cannot be bypassed by simply not sending the header.
        content_type = audio.content_type or ""
        if not content_type:
            content_type = detect_audio_mime_type(audio_bytes) or ""
        if not content_type or content_type not in ALLOWED_AUDIO_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Unsupported or unrecognised audio format"
                       + (f": {content_type}" if content_type else "")
                       + f". Supported: {', '.join(sorted(ALLOWED_AUDIO_TYPES))}",
            )

        # Pre-decode duration check (Phase 02 / Finding 11) — rejects
        # oversized MP3/OGG before the 25MB→500MB PCM blow-up.
        await precheck_audio_duration(
            audio_bytes,
            content_type,
            float(get_settings().audio_max_duration_sec),
        )

        result = await svc.evaluate(audio_bytes, reference_text.strip())
        return result

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.error("Audio processing error: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error during evaluation")
        raise HTTPException(status_code=500, detail="Internal server error.")
