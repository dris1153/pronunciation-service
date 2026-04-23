"""Goodness of Pronunciation (GOP) scoring service.

Computes per-phoneme and per-word GOP scores by using CTC log-posteriors
from the ASR model and a forced alignment against the expected phoneme
sequence.

GOP formula (log-posterior variant):
    GOP(p) = (1/d) * Σ log P(p | o_t)
where d is the duration (number of frames) assigned to phoneme p.

Frame segmentation uses ``torchaudio.functional.forced_align`` (CTC forced
alignment) for accurate phoneme boundaries.  Falls back to uniform
segmentation when forced alignment cannot be applied (e.g. all phonemes are
OOV or the target sequence is too long for the emission).
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np
import torch
import torchaudio.functional as F
from loguru import logger

from app.models.schemas import (
    GOPResult,
    PhonemeGOP,
    PronunciationLevel,
    WordGOP,
)
from app.services.asr_service import ASRService, get_asr_service
from app.services.ipa_service import IPAService, get_ipa_service
from app.utils.audio import is_silent
from app.utils.text import text_to_words

# ── Helpers ──────────────────────────────────────────────────────────────────

# Mapping from IPA phonemes → Wav2Vec2 vocabulary tokens (upper-case letters)
# This is a simplified mapping; complex IPA symbols map to the closest letter.
_IPA_TO_WAV2VEC: dict[str, str] = {
    "ɑ": "A", "æ": "A", "ʌ": "U", "ə": "A", "ɔ": "O",
    "aʊ": "A", "aɪ": "I", "b": "B", "tʃ": "C", "d": "D",
    "ð": "D", "ɛ": "E", "ɝ": "E", "ɚ": "E", "eɪ": "E",
    "f": "F", "ɡ": "G", "h": "H", "ɪ": "I", "i": "E",
    "dʒ": "J", "k": "K", "l": "L", "m": "M", "n": "N",
    "ŋ": "N", "oʊ": "O", "ɔɪ": "O", "p": "P", "ɹ": "R",
    "s": "S", "ʃ": "S", "t": "T", "θ": "T", "ʊ": "U",
    "u": "U", "v": "V", "w": "W", "j": "Y", "z": "Z",
    "ʒ": "Z",
}

# ── GOP normalisation constants ──────────────────────────────────────────────
# Empirically calibrated from CTC log-posteriors.  Correctly pronounced
# phonemes typically land in [-25, -3]; values outside are clamped.
_FLOOR = -25.0   # raw score considered 0 % (very poor pronunciation)
_CEIL  = -3.0    # raw score considered 100 % (excellent pronunciation)
_RANGE = _CEIL - _FLOOR  # 22.0


def _quality_from_gop(score: float) -> PronunciationLevel:
    """Map a normalised GOP score [0-100] to a quality level."""
    if score >= 80:
        return PronunciationLevel.EXCELLENT
    if score >= 60:
        return PronunciationLevel.GOOD
    if score >= 40:
        return PronunciationLevel.FAIR
    return PronunciationLevel.POOR


def _normalise_gop(raw: float) -> float:
    """Convert raw log-prob GOP (negative) to a 0–100 scale.

    Empirically calibrated: CTC log-probs for correctly pronounced phonemes
    typically fall in the range **-25** (very poor) to **-3** (excellent).
    Even "perfect" TTS audio rarely produces raw scores above -2 because
    CTC softmax always distributes probability mass across the full vocab.

    The wider range [-25, -3] (instead of [-25, -5]) means the scale is
    stricter — speakers must achieve higher posterior probabilities to score
    near 100, aligning better with Azure's accuracy expectations for
    non-native speakers.
    """
    clamped = max(min(raw, _CEIL), _FLOOR)
    score = ((clamped - _FLOOR) / _RANGE) * 100.0
    return round(min(max(score, 0.0), 100.0), 2)


class GOPService:
    """Compute Goodness-of-Pronunciation scores."""

    def __init__(
        self,
        asr: ASRService | None = None,
        ipa: IPAService | None = None,
    ) -> None:
        self._asr = asr or get_asr_service()
        self._ipa = ipa or get_ipa_service()
        self._vocab = self._asr.get_vocab()

        # CTC blank index — Wav2Vec2 uses <pad> at index 0
        self._blank_idx: int = self._vocab.get("<pad>", 0)
        logger.info("GOPService initialised (blank_idx={})", self._blank_idx)

    # ── public API ───────────────────────────────────────────

    def score(
        self,
        waveform: np.ndarray,
        sr: int,
        reference_text: str,
    ) -> GOPResult:
        """Compute GOP scores for the given audio vs reference text.

        Frame segmentation strategy:
        1. Map IPA phonemes → Wav2Vec2 token indices.
        2. Use ``torchaudio.functional.forced_align`` to obtain CTC-optimal
           per-frame labels.  This gives accurate phoneme boundaries that
           respect actual durations rather than splitting frames equally.
        3. Fall back to uniform segmentation only when forced alignment
           cannot be applied (all OOV, or sequence constraint violated).
        """
        # ── Silent audio guard ──
        # Skip expensive ASR/CTC inference entirely for silent recordings.
        # GOP scoring on silence produces arbitrary log-prob noise that maps
        # to misleading non-zero scores, so we short-circuit here and return
        # a zero-score result with POOR quality for every phoneme.
        if is_silent(waveform):
            logger.debug("Silent audio detected in GOP scoring — returning zero scores")
            words = text_to_words(reference_text)
            word_scores: list[WordGOP] = []
            for w in words:
                phonemes = self._ipa.word_to_phoneme_list(w)
                ph_scores = [
                    PhonemeGOP(phoneme=p, gop_score=0.0, quality=PronunciationLevel.POOR)
                    for p in phonemes
                ]
                word_scores.append(
                    WordGOP(
                        word=w,
                        phoneme_scores=ph_scores,
                        word_gop_score=0.0,
                        quality=PronunciationLevel.POOR,
                    )
                )
            return GOPResult(
                word_scores=word_scores,
                overall_gop_score=0.0,
                overall_quality=PronunciationLevel.POOR,
                sample_rate=sr,
                total_frames=0,
            )

        # get_emission() returns (1, T, V) — the batched form expected by
        # torchaudio.functional.forced_align.  We derive the (T, V) log_probs
        # for _compute_phoneme_gop by squeezing the batch dimension here so
        # that get_emission() is called exactly once instead of duplicating
        # the log-softmax work inside get_ctc_log_probs().
        emission = self._asr.get_emission(waveform, sr)   # (1, T, V)
        log_probs = emission.squeeze(0)                    # (T, V)
        words = text_to_words(reference_text)

        # Build flat phoneme list: (word_index, word, ipa_phoneme)
        total_phonemes: list[tuple[int, str, str]] = []
        for wi, w in enumerate(words):
            phonemes = self._ipa.word_to_phoneme_list(w)
            for p in phonemes:
                total_phonemes.append((wi, w, p))

        if not total_phonemes:
            return GOPResult(
                word_scores=[],
                overall_gop_score=0.0,
                overall_quality=PronunciationLevel.POOR,
            )

        n_frames = log_probs.size(0)
        n_phonemes = len(total_phonemes)

        # ── Frame boundary computation ──
        boundaries = self._forced_align_boundaries(emission, total_phonemes)
        if boundaries is None:
            # Fallback: uniform segmentation
            logger.debug("Forced alignment unavailable — using uniform segmentation")
            boundaries = self._uniform_boundaries(n_frames, n_phonemes)

        # ── Build per-word GOP ──
        word_scores: list[WordGOP] = []
        all_phoneme_scores: list[float] = []

        current_word_idx = total_phonemes[0][0]
        current_word = total_phonemes[0][1]
        current_word_phoneme_scores: list[PhonemeGOP] = []
        current_word_start = n_frames  # will be min'd down
        current_word_end = 0           # will be max'd up

        for phoneme_pos, (word_idx, word_str, ipa_phoneme) in enumerate(total_phonemes):
            # Flush when word changes
            if word_idx != current_word_idx:
                avg = float(np.mean([p.gop_score for p in current_word_phoneme_scores]))
                word_scores.append(
                    WordGOP(
                        word=current_word,
                        phoneme_scores=current_word_phoneme_scores,
                        word_gop_score=round(avg, 2),
                        quality=_quality_from_gop(avg),
                        start_frame=current_word_start if current_word_start < n_frames else 0,
                        end_frame=current_word_end,
                    )
                )
                current_word_phoneme_scores = []
                current_word_idx = word_idx
                current_word = word_str
                current_word_start = n_frames
                current_word_end = 0

            start, end = boundaries[phoneme_pos]
            # Track word-level frame boundaries (min start, max end)
            if start < end:  # skip OOV zero-width spans
                current_word_start = min(current_word_start, start)
                current_word_end = max(current_word_end, end)

            raw_score = self._compute_phoneme_gop(log_probs, start, end, ipa_phoneme)
            normalised = _normalise_gop(raw_score)
            all_phoneme_scores.append(normalised)

            current_word_phoneme_scores.append(
                PhonemeGOP(
                    phoneme=ipa_phoneme,
                    gop_score=normalised,
                    quality=_quality_from_gop(normalised),
                )
            )

        # Flush last word
        if current_word_phoneme_scores:
            avg = float(np.mean([p.gop_score for p in current_word_phoneme_scores]))
            word_scores.append(
                WordGOP(
                    word=current_word,
                    phoneme_scores=current_word_phoneme_scores,
                    word_gop_score=round(avg, 2),
                    quality=_quality_from_gop(avg),
                    start_frame=current_word_start if current_word_start < n_frames else 0,
                    end_frame=current_word_end,
                )
            )

        overall = round(float(np.mean(all_phoneme_scores)), 2) if all_phoneme_scores else 0.0
        return GOPResult(
            word_scores=word_scores,
            overall_gop_score=overall,
            overall_quality=_quality_from_gop(overall),
            sample_rate=sr,
            total_frames=n_frames,
        )

    # ── alignment strategies ─────────────────────────────────

    def _forced_align_boundaries(
        self,
        emission: torch.Tensor,
        total_phonemes: list[tuple[int, str, str]],
    ) -> list[tuple[int, int]] | None:
        """Use ``torchaudio.functional.forced_align`` to compute frame boundaries.

        Parameters
        ----------
        emission:
            CTC log-probabilities shaped ``(1, T, V)`` — the batched form
            returned by ``ASRService.get_emission()``.  Accepting the batched
            tensor directly avoids an extra ``.unsqueeze(0)`` call here.
        total_phonemes:
            Flat list of ``(word_idx, word, ipa_phoneme)`` tuples.

        Returns a list of ``(start, end)`` pairs for each phoneme, or
        ``None`` when forced alignment cannot be applied.
        """
        n_frames = emission.size(1)  # (1, T, V) → T is dim-1
        # Map IPA phonemes → vocab indices (skip OOV)
        target_indices: list[int] = []
        mappable_mask: list[bool] = []  # True if the phoneme has a vocab mapping

        for _, _, ipa_ph in total_phonemes:
            token = _IPA_TO_WAV2VEC.get(ipa_ph, ipa_ph.upper())
            idx = self._vocab.get(token)
            if idx is not None:
                target_indices.append(idx)
                mappable_mask.append(True)
            else:
                mappable_mask.append(False)

        if not target_indices:
            return None  # All OOV — cannot align

        # forced_align requires: T >= L + n_repeats
        n_repeats = sum(
            1 for i in range(1, len(target_indices)) if target_indices[i] == target_indices[i - 1]
        )
        min_frames = len(target_indices) + n_repeats
        if n_frames < min_frames:
            logger.debug(
                "Forced alignment skipped: T={} < L+repeats={}",
                n_frames, min_frames,
            )
            return None

        # Run forced alignment — emission is already (1, T, V)
        targets = torch.tensor([target_indices], dtype=torch.int32)
        input_lengths = torch.tensor([n_frames], dtype=torch.int32)
        target_lengths = torch.tensor([len(target_indices)], dtype=torch.int32)

        try:
            aligned_labels, aligned_scores = F.forced_align(
                emission,
                targets,
                input_lengths=input_lengths,
                target_lengths=target_lengths,
                blank=self._blank_idx,
            )
        except Exception:
            logger.opt(exception=True).debug("forced_align failed — falling back")
            return None

        # aligned_labels: (1, T) — each frame has a label index (0=blank, or target idx+1)
        # We need to convert this back to per-phoneme boundaries.
        frame_labels = aligned_labels.squeeze(0).tolist()  # list[int], length T

        # Collect frame spans for each target token (1-indexed in aligned output).
        # Label value k>0 means target_indices[k-1] is assigned to that frame.
        # Label 0 means blank.
        #
        # CTC forced alignment guarantees monotonic label assignment — target
        # indices appear in strictly increasing order across frames.  This
        # means we can safely iterate once left-to-right, opening a new span
        # whenever the target index changes, without worrying about
        # non-contiguous or out-of-order label assignments.
        n_targets = len(target_indices)
        target_spans: list[tuple[int, int]] = []  # (start, end) per target token
        current_target = -1
        span_start = 0

        for t, label in enumerate(frame_labels):
            if label > 0:  # non-blank
                target_idx = label - 1
                if target_idx != current_target:
                    if current_target >= 0:
                        target_spans.append((span_start, t))
                    span_start = t
                    current_target = target_idx

        # Close the last span
        if current_target >= 0:
            target_spans.append((span_start, n_frames))

        # Safety check: we must have exactly n_targets spans
        if len(target_spans) != n_targets:
            logger.debug(
                "Forced alignment span count mismatch: {} vs {}",
                len(target_spans), n_targets,
            )
            return None

        # Now map back to the full phoneme list (including OOV phonemes).
        # OOV phonemes get a zero-width span (start==end) — _compute_phoneme_gop
        # will return _FLOOR for them.
        boundaries: list[tuple[int, int]] = []
        target_iter = iter(target_spans)
        for is_mappable in mappable_mask:
            if is_mappable:
                boundaries.append(next(target_iter))
            else:
                # OOV: assign empty span — penalty will be applied
                boundaries.append((0, 0))

        return boundaries

    @staticmethod
    def _uniform_boundaries(
        n_frames: int,
        n_phonemes: int,
    ) -> list[tuple[int, int]]:
        """Distribute frames as evenly as possible across phonemes.

        Remainder frames are spread across the last phonemes (each gets +1).
        """
        base = n_frames // n_phonemes
        remainder = n_frames % n_phonemes
        extra_start = n_phonemes - remainder

        boundaries: list[tuple[int, int]] = []
        pos = 0
        for i in range(n_phonemes):
            frames = base + (1 if i >= extra_start else 0)
            boundaries.append((pos, min(pos + frames, n_frames)))
            pos += frames
        return boundaries

    # ── internals ────────────────────────────────────────────

    def _compute_phoneme_gop(
        self,
        log_probs: torch.Tensor,
        start: int,
        end: int,
        ipa_phoneme: str,
    ) -> float:
        """Compute raw GOP for one phoneme across [start, end) frames.

        When the IPA phoneme cannot be mapped to a Wav2Vec2 vocabulary token
        (OOV), a floor penalty is returned instead of the misleading ``max
        log-prob`` approach which inflated scores for unmapped phonemes.
        """
        if start >= end:
            return _FLOOR

        token = _IPA_TO_WAV2VEC.get(ipa_phoneme, ipa_phoneme.upper())
        token_idx = self._vocab.get(token)

        if token_idx is None:
            # OOV — phoneme has no mapping in the Wav2Vec2 vocabulary.
            # Return floor penalty so the normalised score becomes 0 %
            # rather than an inflated value from max-over-vocab.
            logger.debug("OOV phoneme '{}' → penalty {}", ipa_phoneme, _FLOOR)
            return _FLOOR

        segment_lp = log_probs[start:end, token_idx]
        mean_lp = segment_lp.mean().item()
        return float(mean_lp)


@lru_cache
def get_gop_service() -> GOPService:
    return GOPService()
