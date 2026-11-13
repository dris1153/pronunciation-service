"""Upload validation shared by the v1 and v2 evaluate routes."""
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException, UploadFile
from loguru import logger

from app.core.config import get_settings
from app.core.constants import ALLOWED_AUDIO_TYPES, MAX_UPLOAD_BYTES, MAX_UPLOAD_MB
from app.utils.audio import detect_audio_mime_type, precheck_audio_duration
from app.utils.text import validate_reference_text

T = TypeVar("T")


async def evaluate_upload(
    audio: UploadFile,
    reference_text: str,
    evaluate: Callable[[bytes, str], Awaitable[T]],
) -> T:
    """Validate the upload and reference text, then run ``evaluate(bytes, text)``."""

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

        return await evaluate(audio_bytes, reference_text.strip())

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
