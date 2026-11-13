"""Transcript -> IPA phone labels for the phone CTC model.

The vocabulary is the service's own IPA inventory (values of
``_ARPABET_TO_IPA``), so model output, g2p reference phones and
``_PHONEME_GROUPS`` all share one symbol set. Index 0 is the CTC blank.
"""
from __future__ import annotations

from app.services.ipa_service import _ARPABET_TO_IPA, get_ipa_service
from app.utils.text import text_to_words

BLANK = "<blank>"
VOCAB: list[str] = [BLANK] + sorted(set(_ARPABET_TO_IPA.values()))
PHONE_TO_ID: dict[str, int] = {p: i for i, p in enumerate(VOCAB)}

_word_cache: dict[str, tuple[list[int], int]] = {}


def words_to_ids(text: str) -> tuple[list[int], int]:
    """Phone ids for a transcript and the number of g2p symbols not in VOCAB.

    Unknown symbols (stray punctuation from g2p fallbacks) are dropped and
    counted so the caller can report the rate.
    """
    ids: list[int] = []
    dropped = 0
    ipa = get_ipa_service()
    for word in text_to_words(text):
        if word not in _word_cache:
            phones = ipa.word_to_phoneme_list(word)
            known = [PHONE_TO_ID[p] for p in phones if p in PHONE_TO_ID]
            _word_cache[word] = (known, len(phones) - len(known))
        word_ids, word_dropped = _word_cache[word]
        ids.extend(word_ids)
        dropped += word_dropped
    return ids, dropped


def ids_to_phones(ids: list[int]) -> list[str]:
    return [VOCAB[i] for i in ids]
