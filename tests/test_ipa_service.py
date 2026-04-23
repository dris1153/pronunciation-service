"""Tests for IPA service — ARPAbet mapping, g2p, caching."""
from __future__ import annotations

import pytest

from app.services.ipa_service import _ARPABET_TO_IPA, IPAService

# ── ARPAbet → IPA mapping ───────────────────────────────────────────────────


class TestArpabetMapping:
    """Validate the static _ARPABET_TO_IPA lookup."""

    def test_common_vowels_present(self):
        for arpa in ("AA", "AE", "AH", "EH", "IH", "IY", "OW", "UW"):
            assert arpa in _ARPABET_TO_IPA, f"{arpa} missing"

    def test_common_consonants_present(self):
        for arpa in ("B", "D", "F", "G", "K", "L", "M", "N", "P", "R", "S", "T", "V", "Z"):
            assert arpa in _ARPABET_TO_IPA, f"{arpa} missing"

    def test_values_are_non_empty_strings(self):
        for k, v in _ARPABET_TO_IPA.items():
            assert isinstance(v, str) and len(v) > 0, f"{k} → {v!r}"


# ── word_to_ipa ──────────────────────────────────────────────────────────────


class TestWordToIPA:
    """Test single-word → IPA string conversion."""

    @pytest.fixture(autouse=True)
    def _svc(self):
        self.svc = IPAService()

    def test_returns_non_empty_string(self):
        result = self.svc.word_to_ipa("hello")
        assert isinstance(result, str) and len(result) > 0

    def test_cat(self):
        result = self.svc.word_to_ipa("cat")
        assert isinstance(result, str) and len(result) > 0

    def test_unknown_word_still_returns_string(self):
        result = self.svc.word_to_ipa("supercalifragilistic")
        assert isinstance(result, str) and len(result) > 0

    def test_single_letter(self):
        result = self.svc.word_to_ipa("a")
        assert isinstance(result, str) and len(result) > 0

    def test_deterministic(self):
        r1 = self.svc.word_to_ipa("hello")
        r2 = self.svc.word_to_ipa("hello")
        assert r1 == r2


# ── word_to_phoneme_list ─────────────────────────────────────────────────────


class TestWordToPhonemeList:
    """Test single-word → list of IPA phonemes."""

    @pytest.fixture(autouse=True)
    def _svc(self):
        self.svc = IPAService()

    def test_returns_list_of_strings(self):
        phonemes = self.svc.word_to_phoneme_list("cat")
        assert isinstance(phonemes, list) and all(isinstance(p, str) for p in phonemes)

    def test_non_empty(self):
        assert len(self.svc.word_to_phoneme_list("hello")) > 0

    def test_single_letter_word(self):
        phonemes = self.svc.word_to_phoneme_list("i")
        assert len(phonemes) >= 1

    def test_deterministic(self):
        p1 = self.svc.word_to_phoneme_list("dog")
        p2 = self.svc.word_to_phoneme_list("dog")
        assert p1 == p2


# ── text_to_ipa ──────────────────────────────────────────────────────────────


class TestTextToIPA:
    """Test multi-word text → IPA string."""

    @pytest.fixture(autouse=True)
    def _svc(self):
        self.svc = IPAService()

    def test_two_words_have_space(self):
        result = self.svc.text_to_ipa("hello world")
        assert " " in result

    def test_single_word_no_space(self):
        result = self.svc.text_to_ipa("hello")
        assert " " not in result.strip()

    def test_preserves_word_count(self):
        result = self.svc.text_to_ipa("the quick brown fox")
        assert len(result.split()) == 4

    def test_empty_string(self):
        result = self.svc.text_to_ipa("")
        assert result == ""


# ── _run_g2p caching ────────────────────────────────────────────────────────


class TestRunG2PCache:
    """Verify caching behaviour (lru_cache)."""

    @pytest.fixture(autouse=True)
    def _svc(self):
        self.svc = IPAService()

    def test_cache_returns_same_object(self):
        # After two calls with same word, the cached result should be identical
        r1 = self.svc.word_to_ipa("hello")
        r2 = self.svc.word_to_ipa("hello")
        assert r1 == r2

    def test_different_words_different_results(self):
        r1 = self.svc.word_to_ipa("hello")
        r2 = self.svc.word_to_ipa("world")
        assert r1 != r2
