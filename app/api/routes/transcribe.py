"""Audio transcription API routes."""
# NOTE: no `from __future__ import annotations` — slowapi's wrapper breaks
# FastAPI's UploadFile forward-ref resolution when annotations are deferred.

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from loguru import logger

from app.api.dependencies import verify_api_key
from app.api.middleware import limiter
from app.core.config import get_settings
from app.core.constants import ALLOWED_AUDIO_TYPES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from app.models.schemas import ErrorResponse, TranscribeResponse
from app.services.asr_service import get_asr_service
from app.utils.audio import (
    detect_audio_mime_type,
    is_silent,
    load_audio_from_bytes,
    normalize_audio,
    precheck_audio_duration,
    validate_audio_duration,
)

router = APIRouter(prefix="/api/v1", tags=["transcription"])


def _transcribe_rate() -> str:
    return f"{get_settings().rate_limit_transcribe_per_minute}/minute"


def _transcribe_sync(audio_bytes: bytes) -> tuple[str, float]:
    """Run ASR transcription in a sync context (for use with run_in_executor).

    Returns ``(transcription, duration_sec)``.
    """
    waveform, sr = load_audio_from_bytes(audio_bytes)
    validate_audio_duration(waveform, sr)

    # Silent audio guard — skip ASR inference on silence to avoid
    # hallucinated transcriptions from noise/zero-energy audio.
    if is_silent(waveform):
        duration_sec = round(len(waveform) / sr, 2)
        return "", duration_sec

    waveform = normalize_audio(waveform)

    asr = get_asr_service()
    transcription = asr.transcribe(waveform, sr)
    duration_sec = round(len(waveform) / sr, 2)

    return transcription, duration_sec


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": ErrorResponse, "description": "Internal error"},
        503: {"model": ErrorResponse, "description": "Server busy (queue full)"},
        504: {"model": ErrorResponse, "description": "Request timeout"},
    },
    summary="Transcribe audio to text",
    description=(
        "Upload an audio file and receive its plain-text transcription. "
        "Uses the same Wav2Vec2 ASR model as the evaluation endpoint."
    ),
)
@limiter.limit(_transcribe_rate)
async def transcribe_audio(
    request: Request,
    audio: UploadFile = File(..., description="Audio file (wav, mp3, ogg, flac)"),
    _: None = Depends(verify_api_key),
) -> TranscribeResponse:
    """Transcribe audio file to text."""
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

        # Validate content type — fall back to magic-bytes detection when the
        # client omits the Content-Type header to prevent bypass.
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

        # Pre-decode duration check (Phase 02 / Finding 11)
        await precheck_audio_duration(
            audio_bytes,
            content_type,
            float(get_settings().audio_max_duration_sec),
        )

        loop = asyncio.get_running_loop()

        from app.core.concurrency import inference_semaphore

        async with inference_semaphore():
            transcription, duration_sec = await loop.run_in_executor(
                None, _transcribe_sync, audio_bytes
            )

        return TranscribeResponse(
            transcription=transcription,
            duration_sec=duration_sec,
        )

    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        logger.error("Audio processing error: {}", exc)
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Unexpected error during transcription")
        raise HTTPException(status_code=500, detail="Internal server error.")
