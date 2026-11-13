"""Pronunciation evaluation service — orchestrates IPA + ASR + GOP."""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np
from loguru import logger

from app.models.schemas import (
    ErrorType,
    EvaluationResult,
    GOPResult,
    PhonemeResult,
    PronunciationLevel,
    PronunciationResponse,
    WordGOP,
    WordResult,
)
from app.services.asr_service import ASRService, get_asr_service
from app.services.gop_service import GOPService, get_gop_service
from app.services.ipa_service import IPAService, get_ipa_service
from app.services.phoneme_align import (  # noqa: F401 - re-exported for tests
    _DELETE, _EPS, _INSERT, _MATCH, _PHONEME_GROUPS, _SUBSTITUTE, _align_phonemes, _phoneme_similarity,
)
from app.services.prosody_service import ProsodyService, get_prosody_service
from app.utils.audio import (
    is_silent,
    load_audio_from_bytes,
    normalize_audio,
    validate_audio_duration,
)
from app.utils.text import filter_fillers, text_to_words

# ── Internal-only dataclasses used by _build_ipa_result ─────────────────────
# These mirror the old PhonemeDetail / WordIPA Pydantic models but live here
# to keep gop_service.py and schemas.py free of them.


@dataclass
class _PhonemeDetail:
    expected: str
    actual: str
    is_correct: bool
    confidence: float


@dataclass
class _WordIPA:
    word: str
    expected_ipa: str
    actual_ipa: str
    phoneme_details: list[_PhonemeDetail] = field(default_factory=list)
    accuracy: float = 0.0


@dataclass
class _IPAResult:
    reference_ipa: str
    actual_ipa: str
    word_details: list[_WordIPA] = field(default_factory=list)
    overall_ipa_accuracy: float = 0.0


# Safety cap: maximum number of words the DP alignment will process.
# Prevents O(n*m) memory/CPU explosion from pathological inputs.
# Typical reference texts are <50 words; 500 is a generous upper bound.
_MAX_ALIGN_WORDS = 500


def _align_words(
    ref: Sequence[str],
    act: Sequence[str],
) -> list[tuple[str, str, str]]:
    """Align two word sequences using plain Levenshtein DP (cost 1 per op).

    Identical to _align_phonemes but without phonetic similarity — words are
    opaque strings, so partial-match costs make no sense here.

    Returns ``(operation, ref_word, act_word)`` triples (same convention).
    """
    n, m = len(ref), len(act)

    # Guard: truncate excessively long sequences to prevent O(n*m) blow-up.
    if n > _MAX_ALIGN_WORDS:
        logger.warning(
            "Reference truncated from {} to {} words for DP alignment",
            n, _MAX_ALIGN_WORDS,
        )
        ref = ref[:_MAX_ALIGN_WORDS]
        n = _MAX_ALIGN_WORDS
    if m > _MAX_ALIGN_WORDS:
        logger.warning(
            "Transcription truncated from {} to {} words for DP alignment",
            m, _MAX_ALIGN_WORDS,
        )
        act = act[:_MAX_ALIGN_WORDS]
        m = _MAX_ALIGN_WORDS

    dp = np.zeros((n + 1, m + 1), dtype=np.float64)
    for i in range(1, n + 1):
        dp[i][0] = float(i)
    for j in range(1, m + 1):
        dp[0][j] = float(j)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost_sub = 0.0 if ref[i - 1] == act[j - 1] else 1.0
            dp[i][j] = min(
                dp[i - 1][j] + 1.0,
                dp[i][j - 1] + 1.0,
                dp[i - 1][j - 1] + cost_sub,
            )

    ops: list[tuple[str, str, str]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost_sub = 0.0 if ref[i - 1] == act[j - 1] else 1.0
            diag = dp[i - 1][j - 1] + cost_sub
            up   = dp[i - 1][j] + 1.0
            best = dp[i][j]

            if abs(best - diag) < _EPS:
                rw, aw = ref[i - 1], act[j - 1]
                op = _MATCH if rw == aw else _SUBSTITUTE
                ops.append((op, rw, aw))
                i -= 1
                j -= 1
            elif abs(best - up) < _EPS:
                ops.append((_DELETE, ref[i - 1], ""))
                i -= 1
            else:
                ops.append((_INSERT, "", act[j - 1]))
                j -= 1
        elif i > 0:
            ops.append((_DELETE, ref[i - 1], ""))
            i -= 1
        else:
            ops.append((_INSERT, "", act[j - 1]))
            j -= 1

    ops.reverse()
    return ops


# ── Helpers ──────────────────────────────────────────────────────────────────


def _level_from_score(score: float) -> PronunciationLevel:
    if score >= 80:
        return PronunciationLevel.EXCELLENT
    if score >= 60:
        return PronunciationLevel.GOOD
    if score >= 40:
        return PronunciationLevel.FAIR
    return PronunciationLevel.POOR


def _build_feedback(level: PronunciationLevel, score: float) -> str:
    templates = {
        PronunciationLevel.EXCELLENT: (
            "Excellent pronunciation! Your speech closely matches the reference. "
            "Score: {score:.1f}/100."
        ),
        PronunciationLevel.GOOD: (
            "Good pronunciation overall. Minor improvements could be made on "
            "a few sounds. Score: {score:.1f}/100."
        ),
        PronunciationLevel.FAIR: (
            "Fair pronunciation. Several sounds need practice. Focus on the "
            "phonemes marked with low scores. Score: {score:.1f}/100."
        ),
        PronunciationLevel.POOR: (
            "Pronunciation needs significant improvement. Try slowing down and "
            "practising each word individually. Score: {score:.1f}/100."
        ),
    }
    return templates[level].format(score=score)


# ── Error type detection ─────────────────────────────────────────────────────

# Accuracy threshold below which a word is flagged as Mispronunciation.
# Azure Speech uses 60 — we adopt the same threshold.
_MISPRONUNCIATION_THRESHOLD = 60.0


def _detect_error_type(
    alignment_op: str,
    word_accuracy: float,
) -> ErrorType:
    """Classify a word's error type based on alignment operation and accuracy.

    Parameters
    ----------
    alignment_op:
        One of ``"match"``, ``"substitute"``, ``"delete"``, ``"insert"``.
    word_accuracy:
        Word-level IPA accuracy (0–100).  Only meaningful for match/substitute.
    """
    if alignment_op == _DELETE:
        return ErrorType.OMISSION
    if alignment_op == _INSERT:
        return ErrorType.INSERTION
    # match or substitute — check accuracy
    if word_accuracy < _MISPRONUNCIATION_THRESHOLD:
        return ErrorType.MISPRONUNCIATION
    return ErrorType.NONE


def _compute_completeness(
    word_ops: list[tuple[str, str, str]],
    ref_word_count: int,
    word_accuracies: list[float] | None = None,
) -> float:
    """Compute completeness score: ratio of *correctly* pronounced reference words.

    Azure defines completeness as the proportion of reference words the
    speaker produced **correctly** — not merely attempted.  A word is
    "correctly pronounced" when:

    1. The alignment operation is match or substitute (the speaker attempted
       it — not an omission), **and**
    2. The word-level IPA accuracy ≥ ``_MISPRONUNCIATION_THRESHOLD`` (60).

    This means heavily mispronounced words and omitted words both count
    against completeness, which aligns with Azure's behaviour where
    Completeness ≈ 29 when the speaker mangles most words.

    When ``word_accuracies`` is ``None`` (legacy call-sites or tests that
    don't provide per-word accuracy), the old behaviour is preserved: any
    match/substitute counts as pronounced.

    Returns a score in [0, 100].
    """
    if ref_word_count == 0:
        return 100.0

    # Build a list of ref-side ops only (skip INSERTs — they don't consume
    # a reference word).
    ref_ops = [(op, ref_w) for op, ref_w, _ in word_ops if op != _INSERT]

    if word_accuracies is not None:
        # Accuracy-weighted: only count words the speaker pronounced well.
        # ``word_accuracies`` is built from ``ipa_result.word_details`` which
        # contains one entry per ref-side word (match, substitute, **and**
        # delete) — so the list is parallel to ``ref_ops``.  We iterate
        # both in lock-step: match/substitute words check accuracy,
        # delete words are never "pronounced".
        pronounced = 0
        for i, (op, _) in enumerate(ref_ops):
            if op in (_MATCH, _SUBSTITUTE):
                if i < len(word_accuracies) and word_accuracies[i] >= _MISPRONUNCIATION_THRESHOLD:
                    pronounced += 1
            # DELETE ops: word omitted → not pronounced (pronounced += 0)
    else:
        # Legacy behaviour — any attempt counts
        pronounced = sum(1 for op, _ in ref_ops if op in (_MATCH, _SUBSTITUTE))

    return round(min(pronounced / ref_word_count * 100, 100.0), 2)


# ── Fluency scoring ─────────────────────────────────────────────────────────

# Wav2Vec2 CTC hop size: one frame = 320 samples at 16 kHz = 20 ms.
# This value is determined by the model's convolutional feature extractor
# architecture (7 conv layers with stride product = 320) and is constant
# across all Wav2Vec2 variants (base / large / xlsr).  If a non-Wav2Vec2
# model is used, this value MUST be updated to match.
_HOP_SIZE = 320

# Speech-rate target (words/sec).  Native English conversation is ~2.5–4.0
# words/sec.  We use 3.0 as the "ideal" rate; deviations are penalised.
_IDEAL_WPS = 3.0
# Tolerance band: rates within ± this factor of the ideal get full marks.
_WPS_TOLERANCE = 0.5  # i.e. [1.5 .. 4.5] wps → no penalty

# Pause threshold: gap longer than this (in seconds) between words is
# considered an unexpected break.
_UNEXPECTED_BREAK_SEC = 0.8


def _compute_fluency(gop_result: GOPResult) -> float:
    """Compute fluency score from word-level timing (0–100).

    The score is composed of two factors:
    1. **Speech rate** — deviation from the ideal words-per-second rate.
    2. **Pause penalty** — long gaps between consecutive words reduce
       fluency, modelling hesitations / unexpected breaks.

    Parameters
    ----------
    gop_result:
        GOP result containing per-word timing (start_frame, end_frame),
        sample_rate, and total_frames.
    """
    if not gop_result.word_scores:
        return 100.0

    sr = gop_result.sample_rate
    total_frames = gop_result.total_frames

    # Total audio duration in seconds
    total_duration = (total_frames * _HOP_SIZE) / sr if sr > 0 else 0.0
    if total_duration <= 0:
        return 100.0

    # ── Factor 1: speech rate ──
    # Count only words the user *actually spoke* — i.e. words with
    # non-zero frame duration.  gop_result.word_scores is built from
    # reference text, so words the user skipped (omission) will have
    # start_frame == end_frame (zero duration) from uniform fallback.
    # Using the full word_scores count would inflate the rate for
    # partially spoken utterances.
    spoken_words = sum(
        1 for w in gop_result.word_scores if w.end_frame > w.start_frame
    )
    if spoken_words == 0:
        return 0.0
    wps = spoken_words / total_duration
    rate_deviation = abs(wps - _IDEAL_WPS) - _WPS_TOLERANCE
    if rate_deviation <= 0:
        rate_score = 100.0
    else:
        # Every 1 wps deviation beyond tolerance → −20 points
        rate_score = max(100.0 - rate_deviation * 20.0, 0.0)

    # ── Factor 2: pause penalty ──
    # Analyse gaps between consecutive words.  Long gaps reduce fluency.
    pause_penalty = 0.0
    sorted_words = sorted(
        gop_result.word_scores, key=lambda w: w.start_frame
    )

    for i in range(1, len(sorted_words)):
        prev_end = sorted_words[i - 1].end_frame
        curr_start = sorted_words[i].start_frame
        gap_frames = curr_start - prev_end
        if gap_frames > 0:
            gap_sec = (gap_frames * _HOP_SIZE) / sr
            if gap_sec > _UNEXPECTED_BREAK_SEC:
                # Each excess second → −15 points penalty
                pause_penalty += (gap_sec - _UNEXPECTED_BREAK_SEC) * 15.0

    pause_score = max(100.0 - pause_penalty, 0.0)

    # Weighted combination: 40 % rate + 60 % pause.
    # Azure defines fluency as "how closely the speech matches a native
    # speaker's use of silent breaks between words" — pause patterns are
    # the primary signal, speech rate is a secondary proxy.
    fluency = round(0.4 * rate_score + 0.6 * pause_score, 2)
    return min(max(fluency, 0.0), 100.0)


def _detect_unexpected_breaks(
    gop_result: GOPResult,
) -> set[int]:
    """Detect word indices where an unexpected break precedes the word.

    Returns a set of word indices (into gop_result.word_scores) for which
    the gap from the previous word exceeds ``_UNEXPECTED_BREAK_SEC``.
    """
    sr = gop_result.sample_rate
    break_indices: set[int] = set()

    if len(gop_result.word_scores) < 2 or sr == 0:
        return break_indices

    # Sort by start_frame but keep track of the original index so that the
    # returned indices refer to positions in gop_result.word_scores (which
    # is in ref-word order), NOT the sorted order.
    indexed_scores = sorted(
        enumerate(gop_result.word_scores),
        key=lambda pair: pair[1].start_frame,
    )
    for pos in range(1, len(indexed_scores)):
        prev_end = indexed_scores[pos - 1][1].end_frame
        curr_start = indexed_scores[pos][1].start_frame
        gap_frames = curr_start - prev_end
        if gap_frames > 0:
            gap_sec = (gap_frames * _HOP_SIZE) / sr
            if gap_sec > _UNEXPECTED_BREAK_SEC:
                # Use the *original* index, not the sorted position
                break_indices.add(indexed_scores[pos][0])

    return break_indices


# ── Missing-break detection ─────────────────────────────────────────────────

# Punctuation characters that signal an expected pause / prosodic break.
_BREAK_PUNCTUATION = re.compile(r"[.,;:?!]")

# Minimum gap (seconds) expected at a punctuation boundary.  If the speaker
# produces a shorter gap than this at a position where punctuation indicates
# a natural break, the *following* word is flagged as MissingBreak.
# 0.15 s is roughly the shortest perceptible pause in fluent speech.
_MISSING_BREAK_SEC = 0.15


def _find_expected_break_positions(raw_reference: str) -> set[int]:
    """Identify ref-word indices where a break is expected *after* the word.

    Scans the raw (un-normalised) reference text for punctuation characters
    that indicate a prosodic boundary.  Returns the set of word indices
    (0-based, into the normalised word list) where a pause is expected
    **after** that word.

    Algorithm:
    1. Tokenise the raw text the same way ``text_to_words`` does (via
       ``normalise_text``), but *before* normalisation, record which raw
       tokens are followed by break punctuation.
    2. Map those raw token positions to normalised word indices.

    Example::

        raw = "Hello, beautiful world."
        → normalised words: ["hello", "beautiful", "world"]
        → break positions: {0, 2}  (after "hello" and after "world")
    """
    # Split raw text into chunks separated by whitespace, preserving
    # punctuation attached to words (e.g. "Hello," → "Hello,").
    raw_tokens = raw_reference.split()
    if not raw_tokens:
        return set()

    break_after: set[int] = set()
    word_idx = 0  # index into normalised word list

    for raw_tok in raw_tokens:
        # Check if this raw token produces a word after normalisation.
        # normalise_text strips punctuation, so "Hello," → "hello".
        from app.utils.text import normalise_text
        cleaned = normalise_text(raw_tok)
        if not cleaned:
            # Pure punctuation token (e.g. "...") — no word produced.
            continue

        # Does this raw token end with (or contain) break punctuation?
        # We check the *original* token, not the normalised version.
        if _BREAK_PUNCTUATION.search(raw_tok):
            break_after.add(word_idx)

        word_idx += 1

    return break_after


def _detect_missing_breaks(
    gop_result: GOPResult,
    raw_reference: str,
) -> set[int]:
    """Detect word indices where a break was expected but not produced.

    Returns a set of word indices (into ``gop_result.word_scores``) for
    which the reference text has punctuation *before* that word (i.e. after
    the previous word) but the speaker did **not** pause long enough.

    The returned indices refer to the word **after** the expected break —
    consistent with ``_detect_unexpected_breaks`` which flags the word
    *after* a long gap.
    """
    sr = gop_result.sample_rate
    if len(gop_result.word_scores) < 2 or sr == 0:
        return set()

    break_after_positions = _find_expected_break_positions(raw_reference)
    if not break_after_positions:
        return set()

    missing: set[int] = set()
    n_words = len(gop_result.word_scores)

    for pos in break_after_positions:
        # ``pos`` is the word index *after which* a break is expected.
        # We check the gap between word[pos] and word[pos+1].
        next_idx = pos + 1
        if next_idx >= n_words:
            continue  # last word — no following word to check

        prev_end = gop_result.word_scores[pos].end_frame
        curr_start = gop_result.word_scores[next_idx].start_frame
        gap_frames = curr_start - prev_end

        gap_sec = (gap_frames * _HOP_SIZE) / sr if gap_frames > 0 else 0.0

        if gap_sec < _MISSING_BREAK_SEC:
            missing.add(next_idx)

    return missing


class PronunciationService:
    """High-level service that evaluates pronunciation."""

    def __init__(
        self,
        asr: ASRService | None = None,
        ipa: IPAService | None = None,
        gop: GOPService | None = None,
        prosody: ProsodyService | None = None,
    ) -> None:
        self._asr = asr or get_asr_service()
        self._ipa = ipa or get_ipa_service()
        self._gop = gop or get_gop_service()
        self._prosody = prosody or get_prosody_service()
        logger.info("PronunciationService ready")

    # ── public API ───────────────────────────────────────────

    async def evaluate(
        self,
        audio_bytes: bytes,
        reference_text: str,
    ) -> PronunciationResponse:
        """Run full pronunciation evaluation pipeline.

        1. Load & validate audio
        2. Transcribe (ASR)
        3. Convert reference + transcription to IPA
        4. Compare IPA phonemes (sequence alignment)
        5. Compute GOP scores
        6. Build unified response

        CPU-bound ML inference (steps 1–4) is offloaded to a thread-pool
        via ``asyncio.to_thread`` so the async event loop is never blocked.
        ``to_thread`` copies contextvars, so logs from the worker keep the
        middleware's ``request_id`` (``run_in_executor`` would drop it).

        A shared ``asyncio.Semaphore`` limits concurrency to prevent
        resource exhaustion.  Extra requests are **queued**, not rejected.
        """
        from app.core.concurrency import inference_semaphore

        async with inference_semaphore():
            return await asyncio.to_thread(self._evaluate_sync, audio_bytes, reference_text)

    # ── sync pipeline (runs inside thread-pool) ─────────────

    def _evaluate_sync(
        self,
        audio_bytes: bytes,
        reference_text: str,
    ) -> PronunciationResponse:
        """Synchronous implementation of the evaluation pipeline."""
        start = lap_start = time.perf_counter()
        stage_ms: dict[str, float] = {}

        def lap(stage: str) -> None:
            nonlocal lap_start
            now = time.perf_counter()
            stage_ms[stage] = round((now - lap_start) * 1000, 1)
            lap_start = now

        # 1 — Audio
        waveform, sr = load_audio_from_bytes(audio_bytes)
        validate_audio_duration(waveform, sr)

        # Silent audio guard — check on the raw (un-normalised) waveform so
        # that the RMS energy reflects the true recording level.  After
        # normalize_audio() every non-zero signal has RMS ≈ 0.7, making the
        # guard ineffective.  Return a zero-score response immediately to avoid
        # expensive ML inference that would yield arbitrary/misleading results.
        if is_silent(waveform):
            logger.warning("Silent audio detected — returning zero-score response")
            return self._zero_score_response(reference_text)

        waveform = normalize_audio(waveform)
        lap("decode")

        # 2 — Transcribe (one forward pass; the emission is reused for GOP)
        emission = self._asr.get_emission(waveform, sr)
        raw_transcription = self._asr.decode(emission)
        lap("asr")

        # Strip filler / disfluency words (uh, um, …) so they don't create
        # false INSERT operations that unfairly penalise the IPA score.
        # Use text_to_words() — not str.split() — to ensure normalisation is
        # applied consistently (same pipeline as reference text processing).
        # When the entire transcription is fillers (e.g. "uh um"), use an
        # empty string rather than falling back to the raw filler text, which
        # would create spurious INSERT ops and unfairly reduce the score.
        filtered_words = filter_fillers(text_to_words(raw_transcription))
        transcription = " ".join(filtered_words)
        logger.info("Transcription: '{}' (raw: '{}')", transcription, raw_transcription)

        # 3 — Word alignment (computed once, reused by IPA + completeness)
        ref_words = text_to_words(reference_text)
        trans_words = text_to_words(transcription)
        word_ops = _align_words(ref_words, trans_words)

        # 3b — IPA (sequence-alignment based; reuses pre-computed word_ops)
        ipa_result = self._build_ipa_result(reference_text, transcription, word_ops)
        lap("ipa")

        # 4 — GOP
        gop_result = self._gop.score(waveform, sr, reference_text, emission=emission)
        lap("gop")

        # 4b — Prosody
        # Extract word-level durations from CTC timing for speed & rhythm
        # scoring.  Only include words the user actually spoke (non-zero
        # frame span).  Omitted words have start_frame == end_frame.
        gop_sr = gop_result.sample_rate
        word_durations: list[float] = []
        for w in gop_result.word_scores:
            if w.end_frame > w.start_frame and gop_sr > 0:
                dur_sec = ((w.end_frame - w.start_frame) * _HOP_SIZE) / gop_sr
                word_durations.append(dur_sec)

        total_audio_duration = (
            (gop_result.total_frames * _HOP_SIZE) / gop_sr
            if gop_sr > 0 else 0.0
        )

        prosody_result = self._prosody.analyse(
            waveform, sr,
            word_durations=word_durations if word_durations else None,
            total_duration=total_audio_duration,
        )
        lap("prosody")

        # 5 — Sub-scores
        #
        # Accuracy: phoneme-level pronunciation accuracy.
        # Same formula as the previous overall_score (55% IPA + 45% GOP).
        accuracy = round(
            ipa_result.overall_ipa_accuracy * 0.55
            + gop_result.overall_gop_score * 0.45,
            2,
        )

        # Extract per-word IPA accuracies (ref-side words only, same order
        # as word_ops ref entries) for accuracy-weighted completeness.
        word_accuracies = [wd.accuracy for wd in ipa_result.word_details]

        # Completeness: ratio of *correctly* pronounced words to reference words.
        # Words with IPA accuracy below the mispronunciation threshold do NOT
        # count as "complete" — matching Azure's definition.
        completeness = _compute_completeness(word_ops, len(ref_words), word_accuracies)

        # Fluency: speech rate + pause analysis from GOP timing data.
        fluency = _compute_fluency(gop_result)

        # Prosody: pitch variation, range, intonation.
        prosody = prosody_result.prosody_score

        # 6 — Overall score (weighted: lowest score has most weight)
        # Azure formula (scripted, with prosody):
        #   Sort 4 sub-scores low→high as s0, s1, s2, s3:
        #   PronScore = 0.4 * s0 + 0.2 * s1 + 0.2 * s2 + 0.2 * s3
        # This penalises the weakest dimension more heavily than before.
        sub_scores = sorted([accuracy, completeness, fluency, prosody])
        combined = round(
            0.4 * sub_scores[0] + 0.2 * sub_scores[1]
            + 0.2 * sub_scores[2] + 0.2 * sub_scores[3],
            2,
        )
        level = _level_from_score(combined)

        # Detect unexpected breaks for error classification
        break_word_indices = _detect_unexpected_breaks(gop_result)

        # Detect missing breaks — user should have paused at punctuation but didn't
        missing_break_indices = _detect_missing_breaks(gop_result, reference_text)

        results = self._merge_results(
            ipa_result, gop_result, word_ops, break_word_indices, missing_break_indices,
        )

        stage_ms["total"] = round((time.perf_counter() - start) * 1000, 1)
        logger.bind(stage_ms=stage_ms).info("evaluate_timing")

        return PronunciationResponse(
            reference_text=reference_text,
            transcribed_text=transcription,
            results=results,
            accuracy_score=accuracy,
            completeness_score=completeness,
            fluency_score=fluency,
            prosody_score=prosody,
            overall_score=combined,
            level=level,
            feedback=_build_feedback(level, combined),
        )

    def _zero_score_response(self, reference_text: str) -> PronunciationResponse:
        """Return a fully-formed zero-score response for silent / unrecognisable audio.

        Used when ``is_silent()`` detects that the recording contains no
        meaningful speech signal, so expensive ML inference is skipped.
        All sub-scores and overall score are 0; word_details are populated
        from the reference text with OMISSION error type.
        """
        ref_words = text_to_words(reference_text)
        ref_ipa_full = self._ipa.text_to_ipa(reference_text)

        word_details: list[WordResult] = []
        for w in ref_words:
            expected_ipa = self._ipa.word_to_ipa(w)
            word_details.append(
                WordResult(
                    word=w,
                    expected_ipa=expected_ipa,
                    actual_ipa="",
                    phoneme_details=[],
                    ipa_accuracy=0.0,
                    word_gop_score=0.0,
                    word_gop_quality=PronunciationLevel.POOR,
                    error_type=ErrorType.OMISSION,
                )
            )

        results = EvaluationResult(
            reference_ipa=ref_ipa_full,
            actual_ipa="",
            word_details=word_details,
            overall_ipa_accuracy=0.0,
            overall_gop_score=0.0,
            overall_gop_quality=PronunciationLevel.POOR,
        )
        return PronunciationResponse(
            reference_text=reference_text,
            transcribed_text="",
            results=results,
            accuracy_score=0.0,
            completeness_score=0.0,
            fluency_score=0.0,
            prosody_score=0.0,
            overall_score=0.0,
            level=PronunciationLevel.POOR,
            feedback=_build_feedback(PronunciationLevel.POOR, 0.0),
        )

    # ── internals ────────────────────────────────────────────

    def _merge_results(
        self,
        ipa_result: _IPAResult,
        gop_result: GOPResult,
        word_ops: list[tuple[str, str, str]],
        break_word_indices: set[int] | None = None,
        missing_break_indices: set[int] | None = None,
    ) -> EvaluationResult:
        """Merge per-word IPA and GOP data into a single EvaluationResult.

        ``word_ops`` is the word-level alignment from ``_align_words()`` and
        is used to derive per-word ``ErrorType``.

        ``break_word_indices`` — GOP word indices where an unexpected break
        was detected *before* that word.  These override the normal error
        type with ``ErrorType.UNEXPECTED_BREAK``.

        ``missing_break_indices`` — GOP word indices where the user should
        have paused (punctuation boundary) but didn't.  These override the
        normal error type with ``ErrorType.MISSING_BREAK`` only when the
        current error is ``ErrorType.NONE``.

        Design note — GOP vs IPA word index alignment:
        ``ipa_result.word_details`` only contains ref-side words (match,
        substitute, delete — inserts are skipped).  ``gop_result.word_scores``
        is built from the full reference text and is always in ref-word order.
        Using a raw positional index ``i`` over ``ipa_result.word_details`` to
        index into ``gop_result.word_scores`` is therefore correct *as long as*
        both lists iterate the same ref-word sequence — which they do, since
        ``_build_ipa_result`` and ``GOPService.score()`` both start from
        ``text_to_words(reference_text)``.  We make this alignment explicit by
        building ``gop_word_seq`` as a list of GOP words in ref order (one
        entry per ref word, ``None`` for any ref word that has no GOP entry).
        """
        if break_word_indices is None:
            break_word_indices = set()
        if missing_break_indices is None:
            missing_break_indices = set()

        # Build an ordered list of GOP words aligned to the reference word
        # sequence.  ``gop_result.word_scores`` is produced by iterating
        # ``text_to_words(reference_text)`` in order, so a positional list is
        # the correct alignment structure.  We use a list rather than a dict
        # so that repeated words (e.g. "the cat and the dog") are handled
        # correctly — each occurrence gets its own GOP entry.
        gop_word_seq: list[WordGOP | None] = list(gop_result.word_scores) or []

        # Safety assertion: the number of ref-side words from IPA must match
        # the number of GOP word scores.  Both are built from the same
        # ``text_to_words(reference_text)`` call, so a mismatch indicates a
        # bug in the upstream pipeline.
        n_ipa_ref = len(ipa_result.word_details)
        n_gop_ref = len(gop_word_seq)
        if n_ipa_ref != n_gop_ref:
            logger.warning(
                "IPA/GOP ref-word count mismatch: ipa={} gop={}. "
                "break_word_indices may be misaligned.",
                n_ipa_ref, n_gop_ref,
            )

        # Sanitise break_word_indices — discard any index that is out of
        # bounds for the IPA word list to prevent silent mis-classification.
        if break_word_indices:
            valid_range = range(n_ipa_ref)
            invalid = {idx for idx in break_word_indices if idx not in valid_range}
            if invalid:
                logger.warning(
                    "Discarding out-of-range break_word_indices: {} "
                    "(valid range 0..{})",
                    sorted(invalid), n_ipa_ref - 1,
                )
                break_word_indices = break_word_indices - invalid

        # Sanitise missing_break_indices the same way.
        if missing_break_indices:
            valid_range = range(n_ipa_ref)
            invalid = {idx for idx in missing_break_indices if idx not in valid_range}
            if invalid:
                logger.warning(
                    "Discarding out-of-range missing_break_indices: {} "
                    "(valid range 0..{})",
                    sorted(invalid), n_ipa_ref - 1,
                )
                missing_break_indices = missing_break_indices - invalid

        # ``ref_ops`` — alignment ops for ref-side words only (same order as
        # ``ipa_result.word_details`` and ``gop_word_seq``).
        ref_ops: list[str] = [op for op, ref_w, _ in word_ops if op != _INSERT]

        word_details: list[WordResult] = []

        for i, word_ipa in enumerate(ipa_result.word_details):
            # GOP word at position i in the ref sequence
            word_gop: WordGOP | None = gop_word_seq[i] if i < len(gop_word_seq) else None
            gop_ph_iter = iter(word_gop.phoneme_scores if word_gop else [])

            phoneme_results: list[PhonemeResult] = []
            for ph in word_ipa.phoneme_details:
                if ph.expected == "":
                    # INSERT op — no corresponding GOP phoneme score
                    phoneme_results.append(
                        PhonemeResult(
                            expected_ipa="",
                            actual_ipa=ph.actual,
                            is_correct_ipa=False,
                            confidence_ipa=0.0,
                            gop_score=0.0,
                            gop_quality=PronunciationLevel.POOR,
                        )
                    )
                else:
                    gop_ph = next(gop_ph_iter, None)
                    phoneme_results.append(
                        PhonemeResult(
                            expected_ipa=ph.expected,
                            actual_ipa=ph.actual,
                            is_correct_ipa=ph.is_correct,
                            confidence_ipa=ph.confidence,
                            gop_score=gop_ph.gop_score if gop_ph else 0.0,
                            gop_quality=gop_ph.quality if gop_ph else PronunciationLevel.POOR,
                        )
                    )

            # Determine error type from alignment operation + accuracy
            alignment_op = ref_ops[i] if i < len(ref_ops) else _MATCH
            error = _detect_error_type(alignment_op, word_ipa.accuracy)

            # Override with UNEXPECTED_BREAK if timing analysis detected a
            # long pause *before* this word (only when the word itself has
            # no worse error like Omission/Insertion).
            if (
                i in break_word_indices
                and error in (ErrorType.NONE, ErrorType.MISPRONUNCIATION)
            ):
                error = ErrorType.UNEXPECTED_BREAK

            # Override with MISSING_BREAK if the user should have paused at a
            # punctuation boundary but didn't.  Only override when the word
            # currently has no error — don't mask worse errors.
            if i in missing_break_indices and error == ErrorType.NONE:
                error = ErrorType.MISSING_BREAK

            word_details.append(
                WordResult(
                    word=word_ipa.word,
                    expected_ipa=word_ipa.expected_ipa,
                    actual_ipa=word_ipa.actual_ipa,
                    phoneme_details=phoneme_results,
                    ipa_accuracy=word_ipa.accuracy,
                    word_gop_score=word_gop.word_gop_score if word_gop else 0.0,
                    word_gop_quality=word_gop.quality if word_gop else PronunciationLevel.POOR,
                    error_type=error,
                )
            )

        return EvaluationResult(
            reference_ipa=ipa_result.reference_ipa,
            actual_ipa=ipa_result.actual_ipa,
            word_details=word_details,
            overall_ipa_accuracy=ipa_result.overall_ipa_accuracy,
            overall_gop_score=gop_result.overall_gop_score,
            overall_gop_quality=gop_result.overall_quality,
        )

    def _build_ipa_result(
        self,
        reference: str,
        transcription: str,
        word_ops: list[tuple[str, str, str]] | None = None,
    ) -> _IPAResult:
        ref_words = text_to_words(reference)
        trans_words = text_to_words(transcription)

        ref_ipa_full = self._ipa.text_to_ipa(reference)
        act_ipa_full = self._ipa.text_to_ipa(transcription)

        # Cache g2p results to avoid redundant calls
        ref_phoneme_cache: dict[str, tuple[str, tuple[str, ...]]] = {}
        for w in set(ref_words) | set(trans_words):
            ref_phoneme_cache[w] = (
                self._ipa.word_to_ipa(w),
                tuple(self._ipa.word_to_phoneme_list(w)),
            )

        # ── Word-level alignment ──
        # Use plain word-edit-distance DP (no phoneme similarity — words are
        # opaque strings, partial-match costs would be meaningless here).
        # Accept a pre-computed word_ops to avoid redundant DP when the caller
        # (_evaluate_sync) has already aligned the same word sequences.
        if word_ops is None:
            word_ops = _align_words(ref_words, trans_words)

        word_details: list[_WordIPA] = []
        total_correct = 0
        total_ref_phonemes = 0
        total_insertions = 0  # extra phonemes spoken but not expected

        for op, ref_w, trans_w in word_ops:
            if op == _INSERT:
                # Extra word spoken — not in reference.  Penalise by counting
                # its phonemes as insertions (reduces overall accuracy).
                cached = ref_phoneme_cache.get(trans_w) if trans_w else None
                total_insertions += len(cached[1]) if cached else 0
                continue  # Don't add to word_details (not a reference word)

            # op is match, substitute, or delete — all reference-side words
            ref_ipa_str, ref_phonemes = ref_phoneme_cache.get(ref_w, ("", ()))
            if trans_w and trans_w in ref_phoneme_cache:
                act_ipa_str, act_phonemes = ref_phoneme_cache[trans_w]
            else:
                act_ipa_str, act_phonemes = "", ()

            # Phoneme-level alignment within this word pair
            phoneme_ops = _align_phonemes(ref_phonemes, act_phonemes)

            phoneme_details: list[_PhonemeDetail] = []
            correct = 0
            n_ref = 0  # count only ref-side phonemes (match + substitute + delete)

            for p_op, rp, ap in phoneme_ops:
                if p_op == _MATCH:
                    correct += 1
                    n_ref += 1
                    phoneme_details.append(
                        _PhonemeDetail(
                            expected=rp,
                            actual=ap,
                            is_correct=True,
                            confidence=1.0,
                        )
                    )
                elif p_op == _SUBSTITUTE:
                    n_ref += 1
                    phoneme_details.append(
                        _PhonemeDetail(
                            expected=rp,
                            actual=ap,
                            is_correct=False,
                            confidence=_phoneme_similarity(rp, ap),
                        )
                    )
                elif p_op == _DELETE:
                    n_ref += 1
                    phoneme_details.append(
                        _PhonemeDetail(
                            expected=rp,
                            actual="",
                            is_correct=False,
                            confidence=0.0,
                        )
                    )
                elif p_op == _INSERT:
                    # Extra phoneme in actual — record it but don't count
                    # against ref phoneme count.
                    phoneme_details.append(
                        _PhonemeDetail(
                            expected="",
                            actual=ap,
                            is_correct=False,
                            confidence=0.0,
                        )
                    )

            denom = n_ref or 1
            total_correct += correct
            total_ref_phonemes += n_ref

            word_details.append(
                _WordIPA(
                    word=ref_w,
                    expected_ipa=ref_ipa_str,
                    actual_ipa=act_ipa_str,
                    phoneme_details=phoneme_details,
                    accuracy=round(correct / denom * 100, 2),
                )
            )

        # Overall accuracy: penalise insertions by adding them to denominator.
        #
        # Design note — INSERT vs DELETE asymmetry:
        # - Insertions (extra spoken phonemes) inflate the denominator so
        #   overall accuracy drops, reflecting that the speaker added sounds
        #   not present in the reference.
        # - Deletions (omitted reference phonemes) are already counted in
        #   total_ref_phonemes but *not* in total_correct, so they
        #   automatically reduce accuracy — no extra denominator adjustment
        #   is needed.  Adding deletions to the denominator would double-
        #   penalise them.
        denom = max(total_ref_phonemes + total_insertions, 1)
        overall = round(total_correct / denom * 100, 2)

        return _IPAResult(
            reference_ipa=ref_ipa_full,
            actual_ipa=act_ipa_full,
            word_details=word_details,
            overall_ipa_accuracy=overall,
        )


@lru_cache
def get_pronunciation_service() -> PronunciationService:
    return PronunciationService()
