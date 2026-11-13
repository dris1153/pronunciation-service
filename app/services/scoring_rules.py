"""Torch-free scoring rules shared by the v1 and v2 pipelines.

Level / feedback text, word error classification and break detection.
"""
from __future__ import annotations

import re

from app.models.schemas import ErrorType, GOPResult, PronunciationLevel
from app.services.phoneme_align import _DELETE, _INSERT

# Wav2Vec2 CTC hop size: one frame = 320 samples at 16 kHz = 20 ms.
# This value is determined by the model's convolutional feature extractor
# architecture (7 conv layers with stride product = 320) and is constant
# across all Wav2Vec2 variants (base / large / xlsr).  If a non-Wav2Vec2
# model is used, this value MUST be updated to match.
_HOP_SIZE = 320


# Pause threshold: gap longer than this (in seconds) between words is
# considered an unexpected break.
_UNEXPECTED_BREAK_SEC = 0.8


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
