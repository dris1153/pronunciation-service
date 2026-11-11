"""Tests for the pronunciation evaluation service.

Tests the alignment DP, helpers, and the orchestrator with mocked deps.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.models.schemas import ErrorType, GOPResult, PronunciationLevel, ProsodyResult, WordGOP
from app.services.pronunciation_service import (
    _HOP_SIZE,
    _MISSING_BREAK_SEC,
    _UNEXPECTED_BREAK_SEC,
    PronunciationService,
    _align_phonemes,
    _align_words,
    _build_feedback,
    _compute_completeness,
    _compute_fluency,
    _detect_error_type,
    _detect_missing_breaks,
    _detect_unexpected_breaks,
    _find_expected_break_positions,
    _level_from_score,
    _phoneme_similarity,
)
from app.services.prosody_service import (
    _IDEAL_RANGE_ST_MAX,
    _NPVI_CEIL,
    _NPVI_FLOOR,
    ProsodyService,
    _compute_contour_score,
    _compute_range_score,
    _compute_rhythm_score,
    _compute_speed_score,
    _compute_variance_score,
    _hz_to_semitones,
)

# ── _phoneme_similarity ─────────────────────────────────────────────────────


class TestPhonemeSimilarity:
    """Test phonetic similarity scoring."""

    def test_exact_match(self):
        assert _phoneme_similarity("ɛ", "ɛ") == 1.0

    def test_same_group_front_vowels(self):
        # i and ɪ are both front vowels → 0.3
        assert _phoneme_similarity("i", "ɪ") == 0.3

    def test_same_group_plosives(self):
        assert _phoneme_similarity("p", "t") == 0.3

    def test_different_groups(self):
        # p (voiceless plosive) vs m (nasal) → 0.0
        assert _phoneme_similarity("p", "m") == 0.0

    def test_unknown_phoneme(self):
        # Phoneme not in any group
        assert _phoneme_similarity("x", "y") == 0.0

    def test_one_known_one_unknown(self):
        assert _phoneme_similarity("ɛ", "x") == 0.0

    def test_nasals_same_group(self):
        assert _phoneme_similarity("m", "n") == 0.3
        assert _phoneme_similarity("n", "ŋ") == 0.3

    def test_approximants(self):
        assert _phoneme_similarity("l", "ɹ") == 0.3


# ── _level_from_score ────────────────────────────────────────────────────────


class TestLevelFromScore:
    """Test score → level mapping."""

    def test_excellent(self):
        assert _level_from_score(85.0) == PronunciationLevel.EXCELLENT

    def test_good(self):
        assert _level_from_score(65.0) == PronunciationLevel.GOOD

    def test_fair(self):
        assert _level_from_score(45.0) == PronunciationLevel.FAIR

    def test_poor(self):
        assert _level_from_score(30.0) == PronunciationLevel.POOR

    def test_boundary_80(self):
        assert _level_from_score(80.0) == PronunciationLevel.EXCELLENT

    def test_boundary_60(self):
        assert _level_from_score(60.0) == PronunciationLevel.GOOD

    def test_boundary_40(self):
        assert _level_from_score(40.0) == PronunciationLevel.FAIR

    def test_zero(self):
        assert _level_from_score(0.0) == PronunciationLevel.POOR

    def test_hundred(self):
        assert _level_from_score(100.0) == PronunciationLevel.EXCELLENT


# ── _build_feedback ──────────────────────────────────────────────────────────


class TestBuildFeedback:
    """Test feedback string generation."""

    def test_excellent_feedback(self):
        fb = _build_feedback(PronunciationLevel.EXCELLENT, 90.0)
        assert "Excellent" in fb
        assert "90.0" in fb

    def test_good_feedback(self):
        fb = _build_feedback(PronunciationLevel.GOOD, 65.0)
        assert "Good" in fb

    def test_fair_feedback(self):
        fb = _build_feedback(PronunciationLevel.FAIR, 45.0)
        assert "Fair" in fb

    def test_poor_feedback(self):
        fb = _build_feedback(PronunciationLevel.POOR, 20.0)
        assert "needs significant improvement" in fb

    def test_score_in_feedback(self):
        fb = _build_feedback(PronunciationLevel.GOOD, 72.5)
        assert "72.5" in fb


# ── _align_words ─────────────────────────────────────────────────────────────


class TestAlignWords:
    """Test word-level Levenshtein alignment."""

    def test_identical(self):
        ops = _align_words(["hello", "world"], ["hello", "world"])
        assert all(op[0] == "match" for op in ops)
        assert len(ops) == 2

    def test_substitution(self):
        ops = _align_words(["hello"], ["goodbye"])
        assert ops[0][0] == "substitute"
        assert ops[0][1] == "hello"
        assert ops[0][2] == "goodbye"

    def test_deletion(self):
        ops = _align_words(["hello", "world"], ["hello"])
        matches = [o for o in ops if o[0] == "match"]
        deletes = [o for o in ops if o[0] == "delete"]
        assert len(matches) == 1
        assert len(deletes) == 1
        assert deletes[0][1] == "world"

    def test_insertion(self):
        ops = _align_words(["hello"], ["hello", "world"])
        matches = [o for o in ops if o[0] == "match"]
        inserts = [o for o in ops if o[0] == "insert"]
        assert len(matches) == 1
        assert len(inserts) == 1
        assert inserts[0][2] == "world"

    def test_empty_ref(self):
        ops = _align_words([], ["hello"])
        assert len(ops) == 1
        assert ops[0][0] == "insert"

    def test_empty_act(self):
        ops = _align_words(["hello"], [])
        assert len(ops) == 1
        assert ops[0][0] == "delete"

    def test_both_empty(self):
        ops = _align_words([], [])
        assert ops == []

    def test_multiple_operations(self):
        ref = ["the", "cat", "sat"]
        act = ["the", "bat", "on", "sat"]
        ops = _align_words(ref, act)
        op_types = [o[0] for o in ops]
        assert "match" in op_types
        assert "substitute" in op_types or "insert" in op_types


# ── _align_phonemes ──────────────────────────────────────────────────────────


class TestAlignPhonemes:
    """Test phoneme-level alignment with phonetic similarity costs."""

    def test_identical_sequences(self):
        ref = ["h", "ɛ", "l", "oʊ"]
        act = ["h", "ɛ", "l", "oʊ"]
        ops = _align_phonemes(ref, act)
        assert all(op[0] == "match" for op in ops)
        assert len(ops) == 4

    def test_single_substitution(self):
        ref = ["k", "æ", "t"]
        act = ["k", "ɛ", "t"]  # æ → ɛ (same phonetic group)
        ops = _align_phonemes(ref, act)
        subs = [o for o in ops if o[0] == "substitute"]
        assert len(subs) == 1
        assert subs[0][1] == "æ"
        assert subs[0][2] == "ɛ"

    def test_same_group_preferred_over_delete_insert(self):
        """When two phonemes share a group (cost 0.7), DP should prefer
        substitute over delete+insert (cost 2)."""
        ref = ["ɛ"]
        act = ["æ"]
        ops = _align_phonemes(ref, act)
        assert len(ops) == 1
        assert ops[0][0] == "substitute"

    def test_deletion(self):
        ref = ["k", "æ", "t"]
        act = ["k", "t"]
        ops = _align_phonemes(ref, act)
        deletes = [o for o in ops if o[0] == "delete"]
        assert len(deletes) == 1

    def test_insertion(self):
        ref = ["k", "t"]
        act = ["k", "æ", "t"]
        ops = _align_phonemes(ref, act)
        inserts = [o for o in ops if o[0] == "insert"]
        assert len(inserts) == 1

    def test_empty_ref(self):
        ops = _align_phonemes([], ["h", "ɛ"])
        assert all(o[0] == "insert" for o in ops)

    def test_empty_act(self):
        ops = _align_phonemes(["h", "ɛ"], [])
        assert all(o[0] == "delete" for o in ops)

    def test_both_empty(self):
        assert _align_phonemes([], []) == []


# ── PronunciationService._build_ipa_result ───────────────────────────────────


class TestBuildIPAResult:
    """Test the IPA result builder in PronunciationService."""

    @pytest.fixture
    def svc(self, fake_asr, fake_ipa):
        gop = MagicMock()
        prosody = MagicMock()
        return PronunciationService(asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=prosody)

    def test_perfect_match(self, svc):
        result = svc._build_ipa_result("hello", "hello")
        assert result.overall_ipa_accuracy == 100.0
        assert len(result.word_details) == 1
        assert result.word_details[0].word == "hello"

    def test_complete_mismatch(self, svc):
        result = svc._build_ipa_result("hello", "cat")
        assert result.overall_ipa_accuracy < 100.0

    def test_extra_word_penalises_accuracy(self, svc):
        """Transcription has extra word → insertions penalise accuracy."""
        result = svc._build_ipa_result("hello", "hello world")
        # Extra "world" phonemes count as insertions in denominator
        assert result.overall_ipa_accuracy < 100.0

    def test_missing_word(self, svc):
        """Transcription missing a word → deletions reduce accuracy."""
        result = svc._build_ipa_result("hello world", "hello")
        assert result.overall_ipa_accuracy < 100.0
        # word_details includes both reference words
        ref_words = [wd.word for wd in result.word_details]
        assert "hello" in ref_words
        assert "world" in ref_words

    def test_empty_transcription(self, svc):
        result = svc._build_ipa_result("hello", "")
        assert result.overall_ipa_accuracy == 0.0

    def test_ipa_strings_populated(self, svc):
        result = svc._build_ipa_result("hello", "hello")
        assert result.reference_ipa != ""
        assert result.actual_ipa != ""


# ── PronunciationService._evaluate_sync ──────────────────────────────────────


class TestEvaluateSync:
    """Test the sync evaluation pipeline with fully mocked deps."""

    @pytest.fixture
    def svc(self, fake_asr, fake_ipa):
        from app.services.gop_service import GOPService

        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        prosody = MagicMock()
        prosody.analyse.return_value = ProsodyResult(prosody_score=80.0)
        return PronunciationService(asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=prosody)

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_evaluate_returns_response(self, mock_norm, mock_val, mock_load, svc):
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")

        assert result.reference_text == "hello world"
        assert result.transcribed_text == "hello world"
        assert 0.0 <= result.overall_score <= 100.0
        assert isinstance(result.level, PronunciationLevel)
        assert len(result.feedback) > 0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_combined_score_formula(self, mock_norm, mock_val, mock_load, svc):
        """Overall score = weighted 4 sub-scores (lowest has most weight)."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello")

        # accuracy = 55% IPA + 45% GOP
        accuracy = round(
            result.results.overall_ipa_accuracy * 0.55
            + result.results.overall_gop_score * 0.45,
            2,
        )
        assert result.accuracy_score == accuracy

        # overall = weighted sub-scores (sorted low→high: 0.4*s0 + 0.2*s1 + 0.2*s2 + 0.2*s3)
        sub_scores = sorted([
            result.accuracy_score, result.completeness_score,
            result.fluency_score, result.prosody_score,
        ])
        expected = round(
            0.4 * sub_scores[0] + 0.2 * sub_scores[1]
            + 0.2 * sub_scores[2] + 0.2 * sub_scores[3], 2
        )
        assert result.overall_score == expected

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_filler_words_filtered_from_transcription(
        self, mock_norm, mock_val, mock_load, svc
    ):
        """Filler words (uh, um) in ASR output should be stripped before
        alignment so they don't penalise the IPA score."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        # Simulate ASR returning fillers
        svc._asr.decode.return_value = "uh hello um world"

        result = svc._evaluate_sync(b"fake_bytes", "hello world")

        # The transcribed text should have fillers removed
        assert result.transcribed_text == "hello world"

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_filler_only_transcription_uses_raw(
        self, mock_norm, mock_val, mock_load, svc
    ):
        """If transcription is ALL fillers, filtered text is empty string (not raw)."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        svc._asr.decode.return_value = "uh um hmm"

        result = svc._evaluate_sync(b"fake_bytes", "hello")

        # C3 fix: must NOT fall back to raw filler text — use empty string instead.
        # Returning raw filler text would create spurious INSERT operations that
        # unfairly penalise accuracy.
        assert result.transcribed_text == ""

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_runs_asr_model_once(self, mock_norm, mock_val, mock_load, svc):
        """Transcript and GOP must share one emission — no second forward pass."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        svc._evaluate_sync(b"fake_bytes", "hello world")

        svc._asr.get_emission.assert_called_once()
        svc._asr.transcribe.assert_not_called()
        svc._asr.decode.assert_called_once_with(svc._asr.get_emission.return_value)

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_emits_one_stage_timing_record(self, mock_norm, mock_val, mock_load, svc):
        from loguru import logger

        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w
        records: list[dict] = []
        sink_id = logger.add(
            lambda m: records.append(m.record["extra"]["stage_ms"]),
            filter=lambda r: r["message"] == "evaluate_timing",
        )
        try:
            svc._evaluate_sync(b"fake_bytes", "hello world")
        finally:
            logger.remove(sink_id)

        assert len(records) == 1
        assert set(records[0]) == {"decode", "asr", "ipa", "gop", "prosody", "total"}
        assert all(v >= 0 for v in records[0].values())


# ── _detect_error_type ───────────────────────────────────────────────────────


class TestDetectErrorType:
    """Test word-level error classification."""

    def test_match_high_accuracy_is_none(self):
        assert _detect_error_type("match", 90.0) == ErrorType.NONE

    def test_match_low_accuracy_is_mispronunciation(self):
        assert _detect_error_type("match", 50.0) == ErrorType.MISPRONUNCIATION

    def test_substitute_high_accuracy_is_none(self):
        assert _detect_error_type("substitute", 80.0) == ErrorType.NONE

    def test_substitute_low_accuracy_is_mispronunciation(self):
        assert _detect_error_type("substitute", 30.0) == ErrorType.MISPRONUNCIATION

    def test_delete_is_omission(self):
        assert _detect_error_type("delete", 0.0) == ErrorType.OMISSION

    def test_insert_is_insertion(self):
        assert _detect_error_type("insert", 0.0) == ErrorType.INSERTION

    def test_boundary_60_is_none(self):
        """Accuracy exactly at 60 should NOT be flagged as mispronunciation."""
        assert _detect_error_type("match", 60.0) == ErrorType.NONE

    def test_boundary_59_is_mispronunciation(self):
        assert _detect_error_type("match", 59.9) == ErrorType.MISPRONUNCIATION


# ── _compute_completeness ────────────────────────────────────────────────────


class TestComputeCompleteness:
    """Test completeness scoring."""

    def test_all_words_pronounced(self):
        ops = [("match", "hello", "hello"), ("match", "world", "world")]
        assert _compute_completeness(ops, 2) == 100.0

    def test_one_word_omitted(self):
        ops = [("match", "hello", "hello"), ("delete", "world", "")]
        assert _compute_completeness(ops, 2) == 50.0

    def test_all_words_omitted(self):
        ops = [("delete", "hello", ""), ("delete", "world", "")]
        assert _compute_completeness(ops, 2) == 0.0

    def test_substitution_counts_as_pronounced(self):
        """Substitution means the speaker attempted the word — counts as pronounced."""
        ops = [("substitute", "hello", "goodbye"), ("match", "world", "world")]
        assert _compute_completeness(ops, 2) == 100.0

    def test_insertions_ignored(self):
        """Extra spoken words don't affect completeness of reference text."""
        ops = [
            ("match", "hello", "hello"),
            ("insert", "", "extra"),
            ("match", "world", "world"),
        ]
        assert _compute_completeness(ops, 2) == 100.0

    def test_empty_reference(self):
        assert _compute_completeness([], 0) == 100.0

    def test_partial_completeness(self):
        ops = [
            ("match", "the", "the"),
            ("delete", "cat", ""),
            ("match", "sat", "sat"),
        ]
        assert _compute_completeness(ops, 3) == pytest.approx(66.67)

    def test_accuracy_weighted_completeness(self):
        """When word_accuracies is provided, only high-accuracy words count."""
        ops = [
            ("match", "hello", "hello"),
            ("substitute", "world", "ward"),
        ]
        # First word = 100% accuracy, second = 30% (below 60 threshold)
        accs = [100.0, 30.0]
        assert _compute_completeness(ops, 2, accs) == 50.0

    def test_accuracy_weighted_with_delete_in_middle(self):
        """Delete ops interleaved with match ops must not misalign accuracies.

        word_accuracies has one entry per ref-side word (match, substitute,
        AND delete).  Delete entries have accuracy 0.  This test ensures the
        accuracy for 'sat' (100%) is correctly read, not shifted.
        """
        ops = [
            ("match", "the", "the"),      # accuracy 100
            ("delete", "cat", ""),         # accuracy 0  (omitted)
            ("match", "sat", "sat"),       # accuracy 100
        ]
        accs = [100.0, 0.0, 100.0]
        # 2 out of 3 ref words are correctly pronounced
        assert _compute_completeness(ops, 3, accs) == pytest.approx(66.67)

    def test_accuracy_weighted_delete_first(self):
        """Delete as the first op must not shift accuracy indices."""
        ops = [
            ("delete", "hello", ""),       # accuracy 0
            ("match", "world", "world"),   # accuracy 90
        ]
        accs = [0.0, 90.0]
        # Only "world" is correctly pronounced
        assert _compute_completeness(ops, 2, accs) == 50.0


# ── Integration: new fields in _evaluate_sync ────────────────────────────────


class TestEvaluateSyncNewFields:
    """Test that _evaluate_sync populates the new Phase 1 fields."""

    @pytest.fixture
    def svc(self, fake_asr, fake_ipa):
        from app.services.gop_service import GOPService

        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        prosody = MagicMock()
        prosody.analyse.return_value = ProsodyResult(prosody_score=80.0)
        return PronunciationService(asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=prosody)

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_response_has_accuracy_score(self, mock_norm, mock_val, mock_load, svc):
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        assert 0.0 <= result.accuracy_score <= 100.0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_response_has_completeness_score(self, mock_norm, mock_val, mock_load, svc):
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        assert 0.0 <= result.completeness_score <= 100.0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_perfect_match_has_full_completeness(self, mock_norm, mock_val, mock_load, svc):
        """When all words are spoken correctly, completeness should be 100."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        # ASR returns "hello world" (default mock) → completeness = 100
        assert result.completeness_score == 100.0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_missing_word_reduces_completeness(self, mock_norm, mock_val, mock_load, svc):
        """When a word is missing from transcription, completeness < 100."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        # ASR only returns "hello" but reference is "hello world"
        svc._asr.decode.return_value = "hello"
        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        assert result.completeness_score < 100.0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_word_details_have_error_type(self, mock_norm, mock_val, mock_load, svc):
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        for wd in result.results.word_details:
            assert hasattr(wd, "error_type")
            assert isinstance(wd.error_type, ErrorType)

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_omitted_word_gets_omission_error(self, mock_norm, mock_val, mock_load, svc):
        """Word in reference but not spoken → ErrorType.OMISSION."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        svc._asr.decode.return_value = "hello"
        result = svc._evaluate_sync(b"fake_bytes", "hello world")

        error_types = {wd.word: wd.error_type for wd in result.results.word_details}
        assert error_types["world"] == ErrorType.OMISSION


# ── _compute_fluency ─────────────────────────────────────────────────────────


def _make_gop_result(
    word_timings: list[tuple[str, int, int]],
    sample_rate: int = 16000,
    total_frames: int = 100,
) -> GOPResult:
    """Helper: build a GOPResult with word-level timing data."""
    return GOPResult(
        word_scores=[
            WordGOP(
                word=w,
                phoneme_scores=[],
                word_gop_score=80.0,
                quality=PronunciationLevel.EXCELLENT,
                start_frame=s,
                end_frame=e,
            )
            for w, s, e in word_timings
        ],
        overall_gop_score=80.0,
        overall_quality=PronunciationLevel.EXCELLENT,
        sample_rate=sample_rate,
        total_frames=total_frames,
    )


class TestComputeFluency:
    """Test fluency scoring from word-level timing."""

    def test_no_words_returns_100(self):
        gop = GOPResult(
            word_scores=[],
            overall_gop_score=0.0,
            overall_quality=PronunciationLevel.POOR,
            sample_rate=16000,
            total_frames=50,
        )
        assert _compute_fluency(gop) == 100.0

    def test_zero_duration_words_returns_0(self):
        """All words have zero frame duration → 0 spoken words → score 0."""
        gop = _make_gop_result([("hello", 0, 0)], total_frames=50)
        assert _compute_fluency(gop) == 0.0

    def test_normal_speed_high_fluency(self):
        """~3 wps with no pauses → high fluency."""
        # 3 words in 1 second = 3 wps (ideal).
        # 1 second @ 16kHz / 320 hop = 50 frames.
        gop = _make_gop_result(
            [("hello", 0, 15), ("beautiful", 16, 35), ("world", 36, 50)],
            total_frames=50,
        )
        score = _compute_fluency(gop)
        assert score >= 90.0

    def test_very_slow_speech_reduced_fluency(self):
        """~0.5 wps → reduced fluency (rate penalty, but no pause penalty)."""
        # 1 word in 2 seconds = 0.5 wps.
        # 2 sec = 100 frames.
        gop = _make_gop_result([("hello", 0, 100)], total_frames=100)
        score = _compute_fluency(gop)
        assert score < 90.0

    def test_long_pause_reduces_fluency(self):
        """A long gap between words should penalise fluency."""
        # 2 words with a 2-second gap between them.
        # 2 sec gap = 100 frames.
        # Word 1: frames 0-20, Word 2: frames 120-140, total=140
        gop = _make_gop_result(
            [("hello", 0, 20), ("world", 120, 140)],
            total_frames=140,
        )
        score = _compute_fluency(gop)
        # The gap is 100 frames = 2 seconds, well above _UNEXPECTED_BREAK_SEC
        assert score < 90.0

    def test_no_gap_no_pause_penalty(self):
        """Consecutive words with no gap → no pause penalty."""
        gop = _make_gop_result(
            [("hello", 0, 25), ("world", 25, 50)],
            total_frames=50,
        )
        score = _compute_fluency(gop)
        assert score >= 80.0

    def test_score_clamped_to_0_100(self):
        """Fluency score should always be in [0, 100]."""
        gop = _make_gop_result(
            [("hello", 0, 5), ("world", 500, 505)],
            total_frames=505,
        )
        score = _compute_fluency(gop)
        assert 0.0 <= score <= 100.0


# ── _detect_unexpected_breaks ────────────────────────────────────────────────


class TestDetectUnexpectedBreaks:
    """Test break detection from word timing."""

    def test_no_break_with_close_words(self):
        gop = _make_gop_result(
            [("hello", 0, 25), ("world", 26, 50)],
            total_frames=50,
        )
        breaks = _detect_unexpected_breaks(gop)
        assert len(breaks) == 0

    def test_break_detected_with_long_gap(self):
        # Gap of 100 frames = 2 seconds → well above 0.8s threshold
        gop = _make_gop_result(
            [("hello", 0, 25), ("world", 125, 150)],
            total_frames=150,
        )
        breaks = _detect_unexpected_breaks(gop)
        assert 1 in breaks  # word index 1 has a break before it

    def test_single_word_no_break(self):
        gop = _make_gop_result([("hello", 0, 50)], total_frames=50)
        breaks = _detect_unexpected_breaks(gop)
        assert len(breaks) == 0

    def test_multiple_breaks(self):
        # Gaps: word0→word1 = 100 frames (break), word1→word2 = 100 frames (break)
        gop = _make_gop_result(
            [("a", 0, 10), ("b", 110, 120), ("c", 220, 230)],
            total_frames=230,
        )
        breaks = _detect_unexpected_breaks(gop)
        assert 1 in breaks
        assert 2 in breaks

    def test_gap_exactly_at_threshold_no_break(self):
        """Gap at exactly the threshold should NOT be flagged."""
        # _UNEXPECTED_BREAK_SEC = 0.8 → 0.8 * 16000 / 320 = 40 frames
        threshold_frames = int(_UNEXPECTED_BREAK_SEC * 16000 / _HOP_SIZE)
        gop = _make_gop_result(
            [("hello", 0, 10), ("world", 10 + threshold_frames, 10 + threshold_frames + 20)],
            total_frames=10 + threshold_frames + 20,
        )
        breaks = _detect_unexpected_breaks(gop)
        assert len(breaks) == 0

    def test_gap_just_above_threshold_is_break(self):
        """Gap just above the threshold SHOULD be flagged."""
        threshold_frames = int(_UNEXPECTED_BREAK_SEC * 16000 / _HOP_SIZE) + 1
        gop = _make_gop_result(
            [("hello", 0, 10), ("world", 10 + threshold_frames, 10 + threshold_frames + 20)],
            total_frames=10 + threshold_frames + 20,
        )
        breaks = _detect_unexpected_breaks(gop)
        assert 1 in breaks


# ── Phase 2 integration in _evaluate_sync ────────────────────────────────────


class TestEvaluateSyncPhase2:
    """Test fluency score and break detection in the full pipeline."""

    @pytest.fixture
    def svc(self, fake_asr, fake_ipa):
        from app.services.gop_service import GOPService

        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        prosody = MagicMock()
        prosody.analyse.return_value = ProsodyResult(prosody_score=80.0)
        return PronunciationService(asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=prosody)

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_response_has_fluency_score(self, mock_norm, mock_val, mock_load, svc):
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        assert hasattr(result, "fluency_score")
        assert 0.0 <= result.fluency_score <= 100.0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_overall_uses_four_subscores(self, mock_norm, mock_val, mock_load, svc):
        """Overall should now use 4 sub-scores: accuracy, completeness, fluency, prosody."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello")
        sub_scores = sorted([
            result.accuracy_score, result.completeness_score,
            result.fluency_score, result.prosody_score,
        ])
        expected = round(
            0.4 * sub_scores[0] + 0.2 * sub_scores[1]
            + 0.2 * sub_scores[2] + 0.2 * sub_scores[3], 2
        )
        assert result.overall_score == expected


# ── Phase 3: Prosody scoring unit tests ──────────────────────────────────────


class TestComputeVarianceScore:
    """Test _compute_variance_score helper."""

    def test_below_threshold_returns_zero(self):
        assert _compute_variance_score(0.03, 0.05, 0.15) == 0.0

    def test_at_threshold_returns_zero(self):
        assert _compute_variance_score(0.05, 0.05, 0.15) == 0.0

    def test_above_upper_returns_hundred(self):
        assert _compute_variance_score(0.20, 0.05, 0.15) == 100.0

    def test_at_upper_returns_hundred(self):
        assert _compute_variance_score(0.15, 0.05, 0.15) == 100.0

    def test_midpoint(self):
        # midpoint between 0.05 and 0.15 = 0.10 → 50%
        score = _compute_variance_score(0.10, 0.05, 0.15)
        assert abs(score - 50.0) < 0.1


class TestComputeRangeScore:
    """Test _compute_range_score helper."""

    def test_zero_range(self):
        assert _compute_range_score(0.0) == 0.0

    def test_negative_range(self):
        assert _compute_range_score(-1.0) == 0.0

    def test_at_max(self):
        assert _compute_range_score(_IDEAL_RANGE_ST_MAX) == 100.0

    def test_above_max(self):
        assert _compute_range_score(20.0) == 100.0

    def test_half_max(self):
        score = _compute_range_score(_IDEAL_RANGE_ST_MAX / 2)
        assert abs(score - 50.0) < 0.1


class TestComputeContourScore:
    """Test _compute_contour_score helper."""

    def test_short_contour(self):
        # < 3 frames → 0 (too short to judge — conservative score)
        assert _compute_contour_score(np.array([100.0, 120.0])) == 0.0

    def test_flat_contour(self):
        # All same → no direction changes → 0 or very low
        f0 = np.array([100.0] * 20)
        score = _compute_contour_score(f0)
        assert score <= 50.0  # flat contour penalised

    def test_alternating_contour(self):
        # Alternating up/down → many direction changes → high score
        f0 = np.array([100.0, 120.0, 100.0, 120.0, 100.0, 120.0,
                        100.0, 120.0, 100.0, 120.0])
        score = _compute_contour_score(f0)
        assert score >= 80.0

    def test_monotonically_rising(self):
        # Steadily rising → 0 direction changes → low score
        f0 = np.linspace(100, 200, 20)
        score = _compute_contour_score(f0)
        assert score <= 10.0


class TestComputeSpeedScore:
    """Test _compute_speed_score helper."""

    def test_no_words_returns_zero(self):
        assert _compute_speed_score([], 5.0) == 0.0

    def test_zero_duration_returns_zero(self):
        assert _compute_speed_score([0.3, 0.4], 0.0) == 0.0

    def test_ideal_rate_returns_100(self):
        # 3 words in 1 second = 3 wps (ideal)
        score = _compute_speed_score([0.2, 0.3, 0.5], 1.0)
        assert score == 100.0

    def test_within_tolerance_returns_100(self):
        # 3.4 wps → within ±0.5 of 3.0
        # 17 words in 5 seconds = 3.4 wps
        durations = [0.25] * 17
        score = _compute_speed_score(durations, 5.0)
        assert score == 100.0

    def test_too_fast_reduced_score(self):
        # 10 words in 1 second = 10 wps → deviation = |10-3|-0.5 = 6.5
        durations = [0.08] * 10
        score = _compute_speed_score(durations, 1.0)
        assert score < 50.0

    def test_too_slow_reduced_score(self):
        # 1 word in 5 seconds = 0.2 wps → deviation = |0.2-3|-0.5 = 2.3
        score = _compute_speed_score([4.0], 5.0)
        assert score < 60.0

    def test_score_clamped_0_100(self):
        score = _compute_speed_score([0.01] * 100, 1.0)
        assert 0.0 <= score <= 100.0


class TestComputeRhythmScore:
    """Test _compute_rhythm_score (nPVI) helper."""

    def test_single_word_returns_neutral(self):
        """Fewer than 2 words → can't compute nPVI → neutral score 50."""
        assert _compute_rhythm_score([0.5]) == 50.0

    def test_empty_returns_neutral(self):
        assert _compute_rhythm_score([]) == 50.0

    def test_equal_durations_low_score(self):
        """All equal durations → nPVI = 0 → score 0 (flat rhythm)."""
        score = _compute_rhythm_score([0.3, 0.3, 0.3, 0.3, 0.3])
        assert score == 0.0

    def test_high_contrast_high_score(self):
        """Alternating short/long → high nPVI → high score."""
        # e.g. 0.2, 0.6, 0.2, 0.6 — typical stress-timed pattern
        score = _compute_rhythm_score([0.2, 0.6, 0.2, 0.6, 0.2, 0.6])
        assert score >= 70.0

    def test_moderate_contrast(self):
        """Some variation but not extreme → moderate nPVI."""
        score = _compute_rhythm_score([0.3, 0.4, 0.3, 0.5, 0.3, 0.4])
        assert 10.0 <= score <= 80.0

    def test_score_clamped_0_100(self):
        """nPVI above _NPVI_CEIL → clamped at 100."""
        # Extreme contrast
        score = _compute_rhythm_score([0.1, 1.0, 0.1, 1.0, 0.1, 1.0])
        assert 0.0 <= score <= 100.0

    def test_npvi_at_floor(self):
        """nPVI exactly at floor → score 0."""
        # Very slight variation → nPVI close to floor
        score = _compute_rhythm_score([0.30, 0.30, 0.30, 0.30])
        assert score <= 5.0

    def test_npvi_at_ceil(self):
        """nPVI at or above ceil → score 100."""
        # Large alternation to guarantee nPVI >= _NPVI_CEIL
        # nPVI for [0.1, 0.5, 0.1, 0.5]: each pair → |0.4|/0.3 = 1.333
        # nPVI = 100/3 * 3*1.333 = 133.3 → well above 60 → score 100
        score = _compute_rhythm_score([0.1, 0.5, 0.1, 0.5])
        assert score == 100.0


class TestHzToSemitones:
    """Test _hz_to_semitones conversion."""

    def test_single_value(self):
        result = _hz_to_semitones(np.array([100.0]))
        assert result[0] == 0.0

    def test_octave(self):
        # 200 Hz is one octave above 100 Hz → 12 semitones
        result = _hz_to_semitones(np.array([100.0, 200.0]))
        assert abs(result[1] - 12.0) < 0.01

    def test_zero_min(self):
        result = _hz_to_semitones(np.array([0.0, 100.0]))
        assert np.all(result == 0.0)  # graceful handling


class TestProsodyServiceAnalyse:
    """Test ProsodyService.analyse with synthetic audio."""

    @pytest.fixture
    def prosody_svc(self):
        return ProsodyService()

    def test_silent_audio(self, prosody_svc):
        """Silent (all zeros) audio should return low prosody score and is_monotone."""
        waveform = np.zeros(16000, dtype=np.float32)
        result = prosody_svc.analyse(waveform, 16000)
        assert result.is_monotone is True
        assert result.prosody_score <= 40.0

    def test_pure_sine_monotone(self, prosody_svc):
        """A pure sine wave (constant pitch) should be detected as monotone."""
        sr = 16000
        t = np.linspace(0, 2.0, sr * 2, dtype=np.float32)
        waveform = 0.5 * np.sin(2 * np.pi * 200 * t)
        result = prosody_svc.analyse(waveform, sr)
        # Pure sine → very low pitch variation
        assert result.is_monotone is True
        assert result.prosody_score <= 40.0

    def test_varying_pitch(self, prosody_svc):
        """Audio with varying pitch should score higher and not be monotone."""
        sr = 16000
        duration = 2.0
        n = int(sr * duration)
        # Sweep from 100 Hz to 300 Hz (large variation)
        freq = np.linspace(100, 300, n)
        phase = np.cumsum(2 * np.pi * freq / sr)
        waveform = 0.5 * np.sin(phase).astype(np.float32)
        result = prosody_svc.analyse(waveform, sr)
        # Wide pitch sweep → not monotone
        assert result.is_monotone is False
        assert result.prosody_score > 40.0

    def test_result_has_all_fields(self, prosody_svc):
        """ProsodyResult should have all expected fields populated."""
        sr = 16000
        t = np.linspace(0, 1.0, sr, dtype=np.float32)
        waveform = 0.5 * np.sin(2 * np.pi * 200 * t)
        result = prosody_svc.analyse(waveform, sr)
        assert isinstance(result, ProsodyResult)
        assert 0.0 <= result.voiced_ratio <= 1.0
        assert result.pitch_range_semitones >= 0.0
        assert 0.0 <= result.prosody_score <= 100.0

    def test_very_short_audio(self, prosody_svc):
        """Very short audio — few frames, should not crash."""
        waveform = np.random.randn(800).astype(np.float32)  # 50ms
        result = prosody_svc.analyse(waveform, 16000)
        assert 0.0 <= result.prosody_score <= 100.0


class TestEvaluateSyncPhase3:
    """Test prosody integration in the full pipeline."""

    @pytest.fixture
    def svc(self, fake_asr, fake_ipa):
        from app.services.gop_service import GOPService

        gop = GOPService(asr=fake_asr, ipa=fake_ipa)
        prosody = MagicMock()
        prosody.analyse.return_value = ProsodyResult(prosody_score=75.0)
        return PronunciationService(asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=prosody)

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_response_has_prosody_score(self, mock_norm, mock_val, mock_load, svc):
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello world")
        assert hasattr(result, "prosody_score")
        assert result.prosody_score == 75.0

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_overall_uses_four_subscores(self, mock_norm, mock_val, mock_load, svc):
        """Overall should use 4 sub-scores: accuracy, completeness, fluency, prosody."""
        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        result = svc._evaluate_sync(b"fake_bytes", "hello")
        sub_scores = sorted([
            result.accuracy_score, result.completeness_score,
            result.fluency_score, result.prosody_score,
        ])
        expected = round(
            0.4 * sub_scores[0] + 0.2 * sub_scores[1]
            + 0.2 * sub_scores[2] + 0.2 * sub_scores[3], 2
        )
        assert result.overall_score == expected

    @patch("app.services.pronunciation_service.load_audio_from_bytes")
    @patch("app.services.pronunciation_service.validate_audio_duration")
    @patch("app.services.pronunciation_service.normalize_audio")
    def test_prosody_affects_overall(self, mock_norm, mock_val, mock_load, fake_asr, fake_ipa):
        """A low prosody score should lower the overall score."""
        from app.services.gop_service import GOPService

        gop = GOPService(asr=fake_asr, ipa=fake_ipa)

        mock_load.return_value = (np.random.randn(16000).astype(np.float32), 16000)
        mock_norm.side_effect = lambda w: w

        # High prosody
        high_prosody = MagicMock()
        high_prosody.analyse.return_value = ProsodyResult(prosody_score=100.0)
        svc_high = PronunciationService(
            asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=high_prosody
        )
        result_high = svc_high._evaluate_sync(b"fake_bytes", "hello")

        # Low prosody
        low_prosody = MagicMock()
        low_prosody.analyse.return_value = ProsodyResult(prosody_score=20.0)
        svc_low = PronunciationService(
            asr=fake_asr, ipa=fake_ipa, gop=gop, prosody=low_prosody
        )
        result_low = svc_low._evaluate_sync(b"fake_bytes", "hello")

        assert result_low.overall_score < result_high.overall_score


# ── _find_expected_break_positions ───────────────────────────────────────────


class TestFindExpectedBreakPositions:
    """Test punctuation-based break position detection."""

    def test_no_punctuation(self):
        assert _find_expected_break_positions("hello world") == set()

    def test_period_at_end(self):
        # "Hello world." — punctuation after last word → break_after includes
        # word 1.  _detect_missing_breaks later skips it because there is no
        # following word, but _find_expected_break_positions itself reports it.
        assert _find_expected_break_positions("Hello world.") == {1}

    def test_comma_mid_sentence(self):
        # "Hello, world" → break expected after word 0 ("Hello")
        result = _find_expected_break_positions("Hello, world")
        assert result == {0}

    def test_multiple_punctuation(self):
        # "First, second. Third? Fourth"
        # word indices: First=0, second=1, Third=2, Fourth=3
        # Breaks expected after: word 0 (comma), word 1 (period), word 2 (question)
        result = _find_expected_break_positions("First, second. Third? Fourth")
        assert result == {0, 1, 2}

    def test_semicolon_and_colon(self):
        # "One; two: three four"
        result = _find_expected_break_positions("One; two: three four")
        assert result == {0, 1}

    def test_exclamation_mark(self):
        result = _find_expected_break_positions("Stop! Go now")
        assert result == {0}

    def test_multiple_punctuation_marks_same_position(self):
        # "Really?! Yes" — both ? and ! after word 0
        result = _find_expected_break_positions("Really?! Yes")
        assert result == {0}

    def test_empty_string(self):
        assert _find_expected_break_positions("") == set()

    def test_only_punctuation(self):
        # Edge case: string with only punctuation, no words
        assert _find_expected_break_positions("...") == set()

    def test_trailing_comma(self):
        # "Hello," — comma at end → break_after includes word 0.
        # _detect_missing_breaks later skips it (no following word).
        assert _find_expected_break_positions("Hello,") == {0}


# ── _detect_missing_breaks ───────────────────────────────────────────────────


class TestDetectMissingBreaks:
    """Test detection of missing pauses at punctuation boundaries."""

    def test_no_punctuation_no_missing(self):
        gop = _make_gop_result(
            [("hello", 0, 25), ("world", 26, 50)],
            total_frames=50,
        )
        result = _detect_missing_breaks(gop, "hello world")
        assert result == set()

    def test_pause_present_at_comma(self):
        """User paused at the comma → no missing break."""
        # Gap between word 0 and word 1 is 100 frames = 2s — well above 0.15s
        gop = _make_gop_result(
            [("hello", 0, 25), ("world", 125, 150)],
            total_frames=150,
        )
        result = _detect_missing_breaks(gop, "Hello, world")
        assert result == set()

    def test_no_pause_at_comma(self):
        """User did NOT pause at the comma → missing break detected."""
        # Gap between word 0 and word 1 is 1 frame → essentially no pause
        gop = _make_gop_result(
            [("hello", 0, 25), ("world", 26, 50)],
            total_frames=50,
        )
        result = _detect_missing_breaks(gop, "Hello, world")
        assert 1 in result  # word after expected break

    def test_multiple_missing_breaks(self):
        """Multiple punctuation marks with no pauses."""
        gop = _make_gop_result(
            [("a", 0, 10), ("b", 11, 20), ("c", 21, 30)],
            total_frames=30,
        )
        # "A, B. C" — expect breaks after word 0 and word 1
        result = _detect_missing_breaks(gop, "A, B. C")
        assert result == {1, 2}

    def test_word_count_mismatch_returns_empty(self):
        """GOP and reference word count mismatch → return empty set safely."""
        gop = _make_gop_result(
            [("hello", 0, 25)],
            total_frames=25,
        )
        result = _detect_missing_breaks(gop, "Hello, world")
        assert result == set()

    def test_no_words_returns_empty(self):
        gop = GOPResult(
            word_scores=[],
            overall_gop_score=0.0,
            overall_quality=PronunciationLevel.POOR,
            sample_rate=16000,
            total_frames=50,
        )
        result = _detect_missing_breaks(gop, "")
        assert result == set()

    def test_gap_exactly_at_threshold_is_missing(self):
        """Gap at exactly the threshold should be flagged as missing break."""
        # _MISSING_BREAK_SEC = 0.15 → 0.15 * 16000 / 320 = 7.5 → 7 frames
        threshold_frames = int(_MISSING_BREAK_SEC * 16000 / _HOP_SIZE)
        gop = _make_gop_result(
            [("hello", 0, 10), ("world", 10 + threshold_frames, 10 + threshold_frames + 20)],
            total_frames=10 + threshold_frames + 20,
        )
        # Gap == threshold → still missing (we want strictly MORE than threshold)
        result = _detect_missing_breaks(gop, "Hello, world")
        assert 1 in result

    def test_gap_just_above_threshold_not_missing(self):
        """Gap above the threshold → user paused enough → not a missing break."""
        threshold_frames = int(_MISSING_BREAK_SEC * 16000 / _HOP_SIZE) + 2
        gop = _make_gop_result(
            [("hello", 0, 10), ("world", 10 + threshold_frames, 10 + threshold_frames + 20)],
            total_frames=10 + threshold_frames + 20,
        )
        result = _detect_missing_breaks(gop, "Hello, world")
        assert result == set()

