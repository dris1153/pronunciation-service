"""Text normalisation helpers."""
from __future__ import annotations

import re
import unicodedata

from app.core.constants import (
    MAX_REFERENCE_TEXT_LENGTH,
    MAX_REFERENCE_WORD_COUNT,
    MAX_WORD_LENGTH,
)

# Common speech disfluencies / filler words that ASR models may transcribe.
# These carry no linguistic content and should be stripped before alignment
# so they don't penalise the pronunciation score.
#
# Rules for entries:
#   - All tokens must survive normalise_text() (lowercase, no hyphens,
#     no punctuation) — otherwise they can never match.
#   - Wav2Vec2 outputs plain lowercase alphabetic tokens; hyphenated forms
#     such as "uh-huh" are never emitted, so they are excluded here.
FILLER_WORDS: frozenset[str] = frozenset({
    "uh", "um", "uhm", "hmm", "hm", "mm",
    "ah", "eh", "er", "mhm", "umm",
})


def normalise_text(text: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace."""
    text = text.lower().strip()
    text = unicodedata.normalize("NFKD", text)
    # keep only letters, digits, spaces, apostrophes
    text = re.sub(r"[^a-z0-9\s']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def text_to_words(text: str) -> list[str]:
    """Split normalised text into word tokens."""
    return normalise_text(text).split()


def filter_fillers(words: list[str]) -> list[str]:
    """Remove filler / disfluency words from a word list.

    >>> filter_fillers(["hello", "uh", "world"])
    ['hello', 'world']
    """
    return [w for w in words if w not in FILLER_WORDS]


def validate_reference_text(text: str) -> str:
    """Validate user-supplied reference text.

    Defends against DoS via g2p_en runtime amplification on pathological
    inputs (Phase 01 / Finding 10). Raises :class:`ValueError` on:

    - char count > ``MAX_REFERENCE_TEXT_LENGTH``
    - word count > ``MAX_REFERENCE_WORD_COUNT``
    - any single word > ``MAX_WORD_LENGTH``
    - any Unicode control character (category C*)

    Returns the NFKC-normalised text on success.
    """
    text = unicodedata.normalize("NFKC", text)
    if len(text) > MAX_REFERENCE_TEXT_LENGTH:
        raise ValueError(
            f"reference_text exceeds {MAX_REFERENCE_TEXT_LENGTH} characters."
        )
    if any(unicodedata.category(c)[0] == "C" for c in text):
        raise ValueError("reference_text contains control characters.")
    words = text.split()
    if len(words) > MAX_REFERENCE_WORD_COUNT:
        raise ValueError(
            f"reference_text exceeds {MAX_REFERENCE_WORD_COUNT} words."
        )
    if any(len(w) > MAX_WORD_LENGTH for w in words):
        raise ValueError(
            f"reference_text contains a word longer than {MAX_WORD_LENGTH} characters."
        )
    return text
