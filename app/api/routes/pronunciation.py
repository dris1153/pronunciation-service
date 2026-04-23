"""Pronunciation evaluation API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger

from app.api.dependencies import get_pronunciation_svc, verify_api_key
from app.core.constants import ALLOWED_AUDIO_TYPES, MAX_UPLOAD_BYTES
from app.models.schemas import ErrorResponse, PronunciationResponse
from app.services.pronunciation_service import PronunciationService
from app.utils.audio import detect_audio_mime_type

router = APIRouter(prefix="/api/v1", tags=["pronunciation"])


@router.post(
    "/evaluate",
    response_model=PronunciationResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        500: {"model": ErrorResponse, "description": "Internal error"},
    },
    summary="Evaluate pronunciation",
    description=(
        "Upload an audio file and reference text. Returns IPA comparison, "
        "GOP scores, and overall pronunciation feedback. "
        "Requires a valid API key in the **X-API-Key** header."
    ),
)
async def evaluate_pronunciation(
    audio: UploadFile = File(..., description="Audio file (wav, mp3, ogg, flac)"),
    reference_text: str = Form(..., description="Reference text to compare against"),
    svc: PronunciationService = Depends(get_pronunciation_svc),
    _: None = Depends(verify_api_key),
) -> PronunciationResponse:
    """Evaluate pronunciation from an audio file against reference text."""

    if not reference_text.strip():
        raise HTTPException(status_code=400, detail="reference_text must not be empty.")

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
                    f"Maximum allowed size is 25 MB."
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
