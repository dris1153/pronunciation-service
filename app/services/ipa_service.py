"""IPA (International Phonetic Alphabet) conversion service.

Uses **g2p_en** for English grapheme-to-phoneme conversion and maps
ARPAbet symbols to IPA.
"""
from __future__ import annotations

from functools import lru_cache

from loguru import logger

from app.utils.text import normalise_text, text_to_words

# ── ARPAbet → IPA mapping ───────────────────────────────────────────────────

_ARPABET_TO_IPA: dict[str, str] = {
    "AA": "ɑ", "AA0": "ɑ", "AA1": "ɑ", "AA2": "ɑ",
    "AE": "æ", "AE0": "æ", "AE1": "æ", "AE2": "æ",
    "AH": "ʌ", "AH0": "ə", "AH1": "ʌ", "AH2": "ʌ",
    "AO": "ɔ", "AO0": "ɔ", "AO1": "ɔ", "AO2": "ɔ",
    "AW": "aʊ", "AW0": "aʊ", "AW1": "aʊ", "AW2": "aʊ",
    "AY": "aɪ", "AY0": "aɪ", "AY1": "aɪ", "AY2": "aɪ",
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "EH": "ɛ", "EH0": "ɛ", "EH1": "ɛ", "EH2": "ɛ",
    "ER": "ɝ", "ER0": "ɚ", "ER1": "ɝ", "ER2": "ɝ",
    "EY": "eɪ", "EY0": "eɪ", "EY1": "eɪ", "EY2": "eɪ",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "IH": "ɪ", "IH0": "ɪ", "IH1": "ɪ", "IH2": "ɪ",
    "IY": "i", "IY0": "i", "IY1": "i", "IY2": "i",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "OW": "oʊ", "OW0": "oʊ", "OW1": "oʊ", "OW2": "oʊ",
    "OY": "ɔɪ", "OY0": "ɔɪ", "OY1": "ɔɪ", "OY2": "ɔɪ",
    "P": "p",
    "R": "ɹ",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "UH": "ʊ", "UH0": "ʊ", "UH1": "ʊ", "UH2": "ʊ",
    "UW": "u", "UW0": "u", "UW1": "u", "UW2": "u",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}


def _ensure_nltk_data() -> None:
    """Download required NLTK data if not already present."""
    import nltk

    for resource in ("averaged_perceptron_tagger_eng",):
        try:
            nltk.data.find(f"taggers/{resource}")
        except LookupError:
            logger.info("Downloading NLTK resource '{}'…", resource)
            nltk.download(resource, quiet=True)


class IPAService:
    """Converts English text ↔ IPA phonemes."""

    def __init__(self) -> None:
        _ensure_nltk_data()

        # Lazy import to avoid heavy load at module level
        from g2p_en import G2p

        self._g2p = G2p()
        logger.info("IPAService initialised (g2p_en)")

    # ── public API ───────────────────────────────────────────

    def text_to_ipa(self, text: str) -> str:
        """Convert a full sentence to an IPA string (space-separated words)."""
        words = text_to_words(text)
        return " ".join(self.word_to_ipa(w) for w in words)

    def word_to_ipa(self, word: str) -> str:
        """Convert a single word to IPA string.

        Result is cached per word — g2p (neural POS tagger) is called
        at most once per unique word across the entire process lifetime.
        """
        return self._word_to_ipa_cached(normalise_text(word))

    def word_to_phoneme_list(self, word: str) -> list[str]:
        """Return list of IPA phoneme tokens for a word.

        Shares the same cache as word_to_ipa — both representations are
        computed together in one g2p call and stored.
        """
        return list(self._word_to_phoneme_list_cached(normalise_text(word)))

    # ── cached internals ─────────────────────────────────────

    def _word_to_ipa_cached(self, word: str) -> str:
        """Cached IPA string for a normalised word."""
        # Piggyback on the shared g2p result via _run_g2p
        ipa_chars, _ = self._run_g2p(word)
        return "".join(ipa_chars)

    def _word_to_phoneme_list_cached(self, word: str) -> tuple[str, ...]:
        """Cached phoneme list (as tuple for hashability) for a normalised word."""
        _, phonemes = self._run_g2p(word)
        return phonemes

    @lru_cache(maxsize=8192)  # Phase 03 / Finding 7-partial: ~16MB max footprint
    def _run_g2p(self, word: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Run g2p exactly once per unique word and cache the result.

        Returns ``(ipa_chars, phoneme_tuple)`` — both are **immutable** tuples
        so the lru_cache cannot be corrupted by external mutation.

        - ``ipa_chars``    — tuple of IPA characters (join for IPA string)
        - ``phoneme_tuple`` — tuple of IPA phoneme tokens (one per phoneme)

        .. note::

           ``@lru_cache`` on an instance method captures ``self`` as part of
           the cache key.  This is safe here because ``IPAService`` is a
           singleton (via ``get_ipa_service()``), so only one ``self`` value
           ever exists and the cache key space is effectively just ``word``.
           If multiple instances were created, each would maintain a separate
           cache, and the ``self`` reference would prevent garbage collection
           of the instance — but that scenario does not apply in this
           architecture.
        """
        raw = self._g2p(word)
        ipa_chars: list[str] = []
        phonemes: list[str] = []
        for p in raw:
            p_stripped = p.strip()
            if not p_stripped or p_stripped == " ":
                continue
            ipa = _ARPABET_TO_IPA.get(p_stripped, p_stripped.lower())
            ipa_chars.append(ipa)
            phonemes.append(ipa)
        return tuple(ipa_chars), tuple(phonemes)


@lru_cache
def get_ipa_service() -> IPAService:
    return IPAService()
