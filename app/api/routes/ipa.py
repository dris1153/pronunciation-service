"""IPA conversion API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import verify_api_key
from app.models.schemas import ErrorResponse, IPAConvertResponse, WordIPADetail
from app.services.ipa_service import get_ipa_service
from app.utils.text import normalise_text, text_to_words

router = APIRouter(prefix="/api/v1", tags=["pronunciation"])


@router.get(
    "/text-analysis",
    response_model=IPAConvertResponse,
    responses={
        400: {"model": ErrorResponse, "description": "Invalid input"},
        401: {"model": ErrorResponse, "description": "Missing API key"},
        403: {"model": ErrorResponse, "description": "Invalid API key"},
    },
    summary="Analyse text and convert to IPA",
    description=(
        "Analyse English text: convert to IPA (International Phonetic Alphabet) "
        "transcription with per-word breakdown including individual phoneme tokens."
    ),
)
async def text_to_ipa(
    text: str = Query(
        ..., min_length=1, max_length=500, description="English text to convert"
    ),
    _: None = Depends(verify_api_key),
) -> IPAConvertResponse:
    """Convert English text to IPA transcription."""
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
