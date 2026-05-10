"""IPA conversion API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import verify_api_key
from app.api.middleware import limiter
from app.core.config import get_settings
from app.core.constants import MAX_REFERENCE_TEXT_LENGTH
from app.models.schemas import ErrorResponse, IPAConvertResponse, WordIPADetail
from app.services.ipa_service import get_ipa_service
from app.utils.text import normalise_text, text_to_words, validate_reference_text

router = APIRouter(prefix="/api/v1", tags=["pronunciation"])


def _text_analysis_rate() -> str:
    return f"{get_settings().rate_limit_text_analysis_per_minute}/minute"


@router.get(
    "/text-analysis",
    response_model=IPAConvertResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
        422: {"model": ErrorResponse, "description": "Text validation failed"},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
    },
    summary="Analyse text and convert to IPA",
    description=(
        "Analyse English text: convert to IPA (International Phonetic Alphabet) "
        "transcription with per-word breakdown including individual phoneme tokens."
    ),
)
@limiter.limit(_text_analysis_rate)
async def text_to_ipa(
    request: Request,
    text: str = Query(
        ...,
        min_length=1,
        max_length=MAX_REFERENCE_TEXT_LENGTH,
        description="English text to convert",
    ),
    _: None = Depends(verify_api_key),
) -> IPAConvertResponse:
    """Convert English text to IPA transcription."""
    try:
        text = validate_reference_text(text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    normalised = normalise_text(text)
    if not normalised:
        raise HTTPException(status_code=400, detail="Text must contain valid English characters.")

    ipa_svc = get_ipa_service()
    words = text_to_words(text)

    word_details: list[WordIPADetail] = []
    for w in words:
        word_details.append(
            WordIPADetail(
                word=w,
                ipa=ipa_svc.word_to_ipa(w),
                phonemes=ipa_svc.word_to_phoneme_list(w),
            )
        )

    full_ipa = " ".join(wd.ipa for wd in word_details)

    return IPAConvertResponse(
        text=normalised,
        ipa=full_ipa,
        words=word_details,
    )
