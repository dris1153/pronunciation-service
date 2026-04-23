"""Tests for the GOP (Goodness of Pronunciation) scoring service."""
from __future__ import annotations

import numpy as np
import pytest
import torch

from app.models.schemas import PronunciationLevel
from app.services.gop_service import (
    _FLOOR,
    GOPService,
    _normalise_gop,
    _quality_from_gop,
)

# ── _normalise_gop ───────────────────────────────────────────────────────────


class TestNormaliseGOP:
    """Test raw log-prob → [0, 100] mapping."""

    def test_zero_maps_to_100(self):
        assert _normalise_gop(0.0) == 100.0

    def test_minus25_maps_to_0(self):
        assert _normalise_gop(-25.0) == 0.0

    def test_minus15_maps_to_45_45(self):
        assert _normalise_gop(-15.0) == 45.45

    def test_clamped_below_minus25(self):
        """Values below -25 should clamp to 0."""
        assert _normalise_gop(-30.0) == 0.0
        assert _normalise_gop(-50.0) == 0.0
        assert _normalise_gop(-100.0) == 0.0

    def test_positive_clamped_to_100(self):
        """Positive raw scores (unusual) should cap at 100."""
        assert _normalise_gop(5.0) == 100.0

    def test_mid_range(self):
        result = _normalise_gop(-10.0)
        expected = round(((-10.0 - (-25.0)) / 22.0) * 100.0, 2)
        assert result == expected

    def test_ceil_boundary(self):
        """Raw score at ceil (-3) should map to 100."""
        assert _normalise_gop(-3.0) == 100.0


# ── _quality_from_gop ────────────────────────────────────────────────────────


class TestQualityFromGOP:
    """Test score → PronunciationLevel mapping."""

    def test_excellent(self):
        assert _quality_from_gop(90.0) == PronunciationLevel.EXCELLENT
        assert _quality_from_gop(80.0) == PronunciationLevel.EXCELLENT

    def test_good(self):
        assert _quality_from_gop(70.0) == PronunciationLevel.GOOD
        assert _quality_from_gop(60.0) == PronunciationLevel.GOOD

    def test_fair(self):
        assert _quality_from_gop(50.0) == PronunciationLevel.FAIR
        assert _quality_from_gop(40.0) == PronunciationLevel.FAIR

    def test_poor(self):
        assert _quality_from_gop(30.0) == PronunciationLevel.POOR
        assert _quality_from_gop(0.0) == PronunciationLevel.POOR

    def test_boundary_79(self):
        assert _quality_from_gop(79.99) == PronunciationLevel.GOOD

    def test_boundary_59(self):
        assert _quality_from_gop(59.99) == PronunciationLevel.FAIR

    def test_boundary_39(self):
        assert _quality_from_gop(39.99) == PronunciationLevel.POOR


# ── GOPService.score ─────────────────────────────────────────────────────────


class TestGOPServiceScore:
    """Test the full score() method with mocked ASR/IPA."""

    @pytest.fixture
    def gop_service(self, fake_asr, fake_ipa):
        """Create GOPService with mocked dependencies."""
        return GOPService(asr=fake_asr, ipa=fake_ipa)

    def test_returns_gop_result(self, gop_service):
        waveform = np.random.randn(16000).astype(np.float32)
        result = gop_service.score(waveform, 16000, "hello world")

        assert result is not None
        assert hasattr(result, "word_scores")
        assert hasattr(result, "overall_gop_score")
        assert hasattr(result, "overall_quality")

    def test_word_count_matches(self, gop_service):
        waveform = np.random.randn(16000).astype(np.float32)
        result = gop_service.score(waveform, 16000, "hello world")

        assert len(result.word_scores) == 2
        assert result.word_scores[0].word == "hello"
        assert result.word_scores[1].word == "world"

    def test_overall_score_in_range(self, gop_service):
        waveform = np.random.randn(16000).astype(np.float32)
        result = gop_service.score(waveform, 16000, "hello")

        assert 0.0 <= result.overall_gop_score <= 100.0

    def test_phoneme_scores_present(self, gop_service):
        waveform = np.random.randn(16000).astype(np.float32)
        result = gop_service.score(waveform, 16000, "hello")

        for ws in result.word_scores:
            assert len(ws.phoneme_scores) > 0
            for ps in ws.phoneme_scores:
                assert 0.0 <= ps.gop_score <= 100.0
                assert isinstance(ps.quality, PronunciationLevel)

    def test_empty_text_returns_poor(self, gop_service):
        """Empty phoneme list → overall score 0, quality POOR."""
        waveform = np.random.randn(16000).astype(np.float32)
        # Mock word_to_phoneme_list to return empty for any word
        gop_service._ipa.word_to_phoneme_list.side_effect = lambda w: []
        result = gop_service.score(waveform, 16000, "hello")

        assert result.overall_gop_score == 0.0
        assert result.overall_quality == PronunciationLevel.POOR

    def test_single_word_single_phoneme(self, fake_asr, fake_ipa):
        """One phoneme — all frames go to that phoneme (non-silent waveform)."""
        fake_ipa.word_to_phoneme_list.side_effect = lambda w: ["h"]
        # Small emission tensor: (1, T=10, V=32)
        fake_asr.get_emission.return_value = torch.zeros(1, 10, 32)
        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        # Use a non-silent waveform so the silent guard is not triggered
        waveform = np.ones(16000, dtype=np.float32) * 0.1
        result = gop.score(waveform, 16000, "hello")

        assert len(result.word_scores) == 1
        assert len(result.word_scores[0].phoneme_scores) == 1

    def test_duplicate_words_handled(self, gop_service):
        """Duplicate words (e.g. 'the the') must produce separate word entries."""
        waveform = np.random.randn(16000).astype(np.float32)
        result = gop_service.score(waveform, 16000, "the the")

        assert len(result.word_scores) == 2
        assert result.word_scores[0].word == "the"
        assert result.word_scores[1].word == "the"

    def test_silent_waveform_returns_zero_scores(self, fake_asr, fake_ipa):
        """Silent audio (RMS < threshold) must short-circuit ASR and GOP
        inference, returning a zero-score GOPResult without calling
        get_emission() at all."""
        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        # All-zeros waveform → RMS = 0 → is_silent() returns True
        waveform = np.zeros(16000, dtype=np.float32)
        result = gop.score(waveform, 16000, "hello world")

        assert result.overall_gop_score == 0.0
        assert result.overall_quality == PronunciationLevel.POOR
        # get_emission should never be called for silent audio
        fake_asr.get_emission.assert_not_called()
        # Every word and phoneme score must be 0
        for ws in result.word_scores:
            assert ws.word_gop_score == 0.0
            for ps in ws.phoneme_scores:
                assert ps.gop_score == 0.0
                assert ps.quality == PronunciationLevel.POOR


# ── OOV fallback penalty ────────────────────────────────────────────────────


class TestOOVFallback:
    """Verify that OOV (Out-Of-Vocabulary) phonemes receive a floor penalty."""

    @pytest.fixture
    def gop_service(self, fake_asr, fake_ipa):
        return GOPService(asr=fake_asr, ipa=fake_ipa)

    def test_oov_phoneme_returns_floor(self, gop_service):
        """An unmapped phoneme should return _FLOOR, not max log-prob."""
        log_probs = torch.randn(20, 32)
        raw = gop_service._compute_phoneme_gop(log_probs, 0, 10, "☺")
        assert raw == _FLOOR

    def test_oov_normalises_to_zero(self, gop_service):
        """OOV penalty normalises to 0% score."""
        assert _normalise_gop(_FLOOR) == 0.0

    def test_start_ge_end_returns_floor(self, gop_service):
        """Empty frame range should return _FLOOR."""
        log_probs = torch.randn(20, 32)
        assert gop_service._compute_phoneme_gop(log_probs, 5, 5, "h") == _FLOOR
        assert gop_service._compute_phoneme_gop(log_probs, 10, 5, "h") == _FLOOR

    def test_known_phoneme_returns_score(self, gop_service):
        """A mapped phoneme should return a real log-prob, not _FLOOR."""
        log_probs = torch.full((20, 32), -10.0)
        # 'h' maps to 'H' which is in the vocab
        raw = gop_service._compute_phoneme_gop(log_probs, 0, 10, "h")
        assert raw != _FLOOR
        assert isinstance(raw, float)


# ── _uniform_boundaries ─────────────────────────────────────────────────────


class TestUniformBoundaries:
    """Test the uniform frame distribution fallback."""

    def test_even_split(self):
        bounds = GOPService._uniform_boundaries(10, 2)
        assert bounds == [(0, 5), (5, 10)]

    def test_remainder_spread(self):
        # 10 frames, 3 phonemes → 3+3+4
        bounds = GOPService._uniform_boundaries(10, 3)
        assert len(bounds) == 3
        # All frames accounted for
        total = sum(e - s for s, e in bounds)
        assert total == 10

    def test_single_phoneme(self):
        bounds = GOPService._uniform_boundaries(50, 1)
        assert bounds == [(0, 50)]

    def test_more_phonemes_than_frames(self):
        bounds = GOPService._uniform_boundaries(3, 5)
        assert len(bounds) == 5
        # Some phonemes get 0 frames, some get 1
        total = sum(e - s for s, e in bounds)
        assert total == 3


# ── _forced_align_boundaries ────────────────────────────────────────────────


class TestForcedAlignBoundaries:
    """Test the CTC forced alignment boundary computation."""

    @pytest.fixture
    def gop_service(self, fake_asr, fake_ipa):
        return GOPService(asr=fake_asr, ipa=fake_ipa)

    def test_all_oov_returns_none(self, gop_service):
        """When every phoneme is OOV, forced alignment should return None."""
        emission = torch.randn(1, 50, 32)
        # Use phonemes that have no mapping
        total_phonemes = [(0, "x", "☺"), (0, "x", "★")]
        result = gop_service._forced_align_boundaries(emission, total_phonemes)
        assert result is None

    def test_returns_boundaries_or_none(self, gop_service):
        """With valid phonemes, should return list of boundaries or None
        (if frames are too few)."""
        emission = torch.randn(1, 50, 32)
        total_phonemes = [(0, "hello", "h"), (0, "hello", "ɛ")]
        result = gop_service._forced_align_boundaries(emission, total_phonemes)
        # Could be None (random log_probs may cause issues) or valid boundaries
        if result is not None:
            assert len(result) == 2
            for start, end in result:
                assert start >= 0
                assert end >= start

    def test_forced_align_succeeds_with_structured_log_probs(self, fake_asr, fake_ipa):
        """Forced alignment should succeed (not fall back) when log_probs have
        a clear dominant token per region.

        We build an emission (1, T=50, V=32) where:
        - frames  0-24 strongly favour token H  (vocab index 12)
        - frames 25-49 strongly favour token E  (vocab index  9)

        The phoneme list [h, ɛ] maps to [H=12, E=9] via _IPA_TO_WAV2VEC.
        With such unambiguous log-probs the CTC forced-align algorithm can
        resolve the boundaries deterministically and must return exactly 2
        spans — verifying that the non-fallback code path is exercised.
        """
        # Build a (1, 50, 32) emission filled with a very low background value.
        n_frames, n_vocab = 50, 32
        emission = torch.full((1, n_frames, n_vocab), -20.0)

        # Vocab indices (A=5 … Z=30)
        H_IDX = 12   # chr(65 + 7) = 'H'
        E_IDX =  9   # chr(65 + 4) = 'E'

        # Make H dominant for first half, E dominant for second half.
        emission[0, :25, H_IDX] = -1.0
        emission[0, 25:, E_IDX] = -1.0

        fake_asr.get_emission.return_value = emission
        fake_ipa.word_to_phoneme_list.side_effect = lambda w: ["h", "ɛ"]

        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        total_phonemes = [(0, "he", "h"), (0, "he", "ɛ")]

        result = gop._forced_align_boundaries(emission, total_phonemes)

        # Forced alignment must succeed (not return None) with structured input
        assert result is not None, (
            "forced_align fell back to None even with unambiguous log_probs; "
            "verify the forced_align code path is being reached"
        )
        assert len(result) == 2

        # Both spans must be valid
        for start, end in result:
            assert start >= 0
            assert end >= start

        # The first span should cover the H-dominant region (frames 0-24)
        # and the second span should cover the E-dominant region (frames 25-49).
        # We allow some slack at boundaries since CTC may place the transition
        # one frame earlier or later.
        first_start, first_end = result[0]
        second_start, second_end = result[1]
        assert first_start == 0, "First phoneme must start at frame 0"
        assert second_end == n_frames, "Last phoneme must end at the final frame"
        assert first_end == second_start, "Spans must be contiguous"
