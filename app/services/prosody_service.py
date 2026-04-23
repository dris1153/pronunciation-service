"""Prosody analysis service — pitch extraction and intonation scoring."""
from __future__ import annotations

from functools import lru_cache

import librosa
import numpy as np
from loguru import logger

from app.core.config import get_settings
from app.models.schemas import ProsodyResult

# ── Constants ────────────────────────────────────────────────────────────────

# pyin hop length — 512 samples at 16 kHz ≈ 32 ms per frame.
# Matches librosa default (frame_length // 4 = 2048 // 4 = 512).
_PYIN_HOP_LENGTH = 512

# Ideal pitch range in semitones for conversational English speech.
# Native speakers typically span 6–15 semitones in a phrase.
_IDEAL_RANGE_ST_MIN = 6.0   # below this → narrow / monotone
_IDEAL_RANGE_ST_MAX = 15.0  # above this → full marks (natural variation)

# Minimum voiced ratio — if less than this fraction of frames are voiced,
# the audio likely contains too much silence or noise for reliable prosody.
_MIN_VOICED_RATIO = 0.10

# ── Speed scoring constants ──────────────────────────────────────────────────

# Ideal speech rate (words per second) for conversational English.
# Native English conversation is ~2.5–4.0 wps; 3.0 is the centre target.
_IDEAL_WPS = 3.0

# Tolerance band: rates within ± this value of _IDEAL_WPS → no penalty.
_WPS_TOLERANCE = 0.5

# ── Rhythm scoring constants ────────────────────────────────────────────────

# Normalised Pairwise Variability Index (nPVI) reference values.
# Native English speech (stress-timed) typically has nPVI ~50–70.
# Syllable-timed languages (French, Vietnamese, etc.) have nPVI ~30–40.
# Values below _NPVI_FLOOR → score 0;  values >= _NPVI_CEIL → score 100.
_NPVI_FLOOR = 30.0   # below this → very flat rhythm, score 0
_NPVI_CEIL  = 70.0   # at or above this → excellent stress-timed rhythm


# ── Core analysis ────────────────────────────────────────────────────────────


def _extract_f0(
    waveform: np.ndarray,
    sr: int,
    fmin: float,
    fmax: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract fundamental frequency using probabilistic YIN (pYIN).

    Returns
    -------
    f0 : np.ndarray [shape=(n_frames,)]
        Fundamental frequency per frame (Hz). NaN for unvoiced frames.
    voiced_flag : np.ndarray [shape=(n_frames,)]
        Boolean flags — True for voiced frames.
    voiced_prob : np.ndarray [shape=(n_frames,)]
        Probability of each frame being voiced.
    """
    f0, voiced_flag, voiced_prob = librosa.pyin(
        waveform,
        sr=sr,
        fmin=fmin,
        fmax=fmax,
        hop_length=_PYIN_HOP_LENGTH,
    )
    return f0, voiced_flag, voiced_prob


def _hz_to_semitones(f0_hz: np.ndarray) -> np.ndarray:
    """Convert Hz frequencies to semitones relative to the array minimum.

    Uses 12 * log2(f / f_ref) where f_ref = min(f0_hz).
    """
    f_ref = np.min(f0_hz)
    if f_ref <= 0:
        return np.zeros_like(f0_hz)
    return 12.0 * np.log2(f0_hz / f_ref)


def _compute_variance_score(pitch_cv: float, monotone_threshold: float, cv_upper: float) -> float:
    """Score pitch coefficient of variation (CV).

    CV = std / mean of voiced f0.
    - CV >= cv_upper → 100 (excellent variation)
    - CV == monotone_threshold → 0
    - Linear interpolation between threshold and cv_upper.
    """
    if pitch_cv <= monotone_threshold:
        return 0.0
    if pitch_cv >= cv_upper:
        return 100.0
    # Linear scale from threshold → cv_upper
    return (pitch_cv - monotone_threshold) / (cv_upper - monotone_threshold) * 100.0


def _compute_range_score(range_st: float) -> float:
    """Score pitch range in semitones.

    - range >= _IDEAL_RANGE_ST_MAX → 100
    - range <= 0 → 0
    - Linear interpolation between 0 and _IDEAL_RANGE_ST_MAX.
    """
    if range_st <= 0:
        return 0.0
    if range_st >= _IDEAL_RANGE_ST_MAX:
        return 100.0
    return range_st / _IDEAL_RANGE_ST_MAX * 100.0


def _compute_contour_score(f0_voiced: np.ndarray) -> float:
    """Score intonation contour naturalness.

    Measures how many directional changes (rises/falls) occur in the pitch
    contour.  Monotone speech has very few changes; expressive speech has
    many.

    We compute the fraction of consecutive frame pairs that change direction
    (sign of first-order difference flips).  This is a simple proxy for
    intonation richness.

    - 0 direction changes → 0
    - ≥45% of frames show direction change → 100
    """
    if len(f0_voiced) < 3:
        return 0.0  # too short to judge — be conservative (not "neutral")

    diffs = np.diff(f0_voiced)
    signs = np.sign(diffs)

    # Count sign changes (positive→negative or negative→positive transitions)
    # Ignore zero-crossings where diff == 0
    nonzero_signs = signs[signs != 0]
    if len(nonzero_signs) < 2:
        return 0.0  # too few non-zero diffs to judge reliably

    direction_changes = np.sum(np.abs(np.diff(nonzero_signs)) > 0)
    change_ratio = direction_changes / (len(nonzero_signs) - 1)

    # Scale: 0.45 change ratio → 100 score (stricter than before to match
    # Azure's intonation expectations for native-like speech)
    target = 0.45
    if change_ratio >= target:
        return 100.0
    return change_ratio / target * 100.0


def _compute_speed_score(
    word_durations: list[float],
    total_duration: float,
) -> float:
    """Score speaking speed relative to the ideal rate.

    Parameters
    ----------
    word_durations:
        Duration of each spoken word in seconds.  Only words the user
        actually spoke (duration > 0) should be included.
    total_duration:
        Total audio duration in seconds.

    Returns a score in [0, 100].  100 = rate within the ideal band.
    """
    if not word_durations or total_duration <= 0:
        return 0.0

    wps = len(word_durations) / total_duration
    deviation = abs(wps - _IDEAL_WPS) - _WPS_TOLERANCE
    if deviation <= 0:
        return 100.0
    # Every 1 wps deviation beyond tolerance → −30 points
    return max(100.0 - deviation * 30.0, 0.0)


def _compute_rhythm_score(word_durations: list[float]) -> float:
    """Score rhythm via the normalised Pairwise Variability Index (nPVI).

    nPVI measures the degree of durational contrast between successive
    intervals (here, word durations).  Stress-timed languages like English
    exhibit higher nPVI (~50–70) because stressed and unstressed syllables
    differ markedly in length.  Syllable-timed speakers (e.g. Vietnamese
    native speakers reading English) tend to produce lower nPVI (~30–40)
    because all syllables are roughly equal length.

    Formula (Grabe & Low 2002)::

        nPVI = 100 / (m-1) × Σ |d_k - d_{k+1}| / ((d_k + d_{k+1}) / 2)

    where m = number of intervals, d_k = duration of interval k.

    Parameters
    ----------
    word_durations:
        Durations (in seconds) of consecutive spoken words.  Zero-duration
        entries (omitted words) must be filtered out before calling.

    Returns a score in [0, 100].
    """
    m = len(word_durations)
    if m < 2:
        # Can't compute pairwise variability with fewer than 2 words.
        # Return a neutral score — don't penalise very short utterances.
        return 50.0

    # nPVI calculation
    pvi_sum = 0.0
    for k in range(m - 1):
        d_k = word_durations[k]
        d_next = word_durations[k + 1]
        mean_pair = (d_k + d_next) / 2.0
        if mean_pair > 0:
            pvi_sum += abs(d_k - d_next) / mean_pair

    npvi = 100.0 / (m - 1) * pvi_sum

    # Map nPVI to score: _NPVI_FLOOR → 0, _NPVI_CEIL → 100
    if npvi <= _NPVI_FLOOR:
        return 0.0
    if npvi >= _NPVI_CEIL:
        return 100.0
    return (npvi - _NPVI_FLOOR) / (_NPVI_CEIL - _NPVI_FLOOR) * 100.0


# ── Service class ────────────────────────────────────────────────────────────


class ProsodyService:
    """Analyses prosody (pitch variation, intonation, monotone detection)."""

    def __init__(self) -> None:
        settings = get_settings()
        self._fmin = settings.prosody_pitch_min_hz
        self._fmax = settings.prosody_pitch_max_hz
        self._monotone_threshold = settings.prosody_monotone_threshold
        cv_upper = settings.prosody_pitch_cv_upper
        # Guard: cv_upper must be strictly greater than monotone_threshold,
        # otherwise the variance scoring range collapses to zero and all
        # non-monotone speech would receive 100 (or divide-by-zero).
        if cv_upper <= self._monotone_threshold:
            logger.error(
                "prosody_pitch_cv_upper ({}) must be > prosody_monotone_threshold ({}). "
                "Clamping cv_upper to monotone_threshold + 0.05.",
                cv_upper, self._monotone_threshold,
            )
            cv_upper = self._monotone_threshold + 0.05
        self._cv_upper = cv_upper
        logger.info(
            "ProsodyService ready  fmin={}  fmax={}  monotone_thresh={}  cv_upper={}",
            self._fmin, self._fmax, self._monotone_threshold, self._cv_upper,
        )

    def analyse(
        self,
        waveform: np.ndarray,
        sr: int,
        word_durations: list[float] | None = None,
        total_duration: float = 0.0,
    ) -> ProsodyResult:
        """Run full prosody analysis on a waveform.

        Parameters
        ----------
        waveform : 1-D float32 numpy array (mono, peak-normalised)
        sr : sample rate in Hz (expected 16000)
        word_durations :
            Duration of each spoken word in seconds (from CTC timing).
            Required for speed and rhythm scoring.  When ``None``, those
            sub-scores default to 50 (neutral).
        total_duration :
            Total audio duration in seconds.  Required for speed scoring.

        Returns
        -------
        ProsodyResult with pitch statistics, monotone flag, and score.
        """
        # 1 — Extract f0
        f0, voiced_flag, _ = _extract_f0(waveform, sr, self._fmin, self._fmax)

        # 2 — Gather voiced frames
        voiced_mask = voiced_flag.astype(bool)
        n_total = len(f0)
        n_voiced = int(np.sum(voiced_mask))
        voiced_ratio = n_voiced / n_total if n_total > 0 else 0.0

        # Too few voiced frames → can't compute reliable prosody
        if n_voiced < 2 or voiced_ratio < _MIN_VOICED_RATIO:
            logger.warning(
                "Insufficient voiced frames: {}/{} ({:.1%})",
                n_voiced, n_total, voiced_ratio,
            )
            return ProsodyResult(
                pitch_mean_hz=0.0,
                pitch_std_hz=0.0,
                pitch_range_semitones=0.0,
                voiced_ratio=round(voiced_ratio, 4),
                is_monotone=True,
                prosody_score=0.0,
            )

        f0_voiced = f0[voiced_mask]

        # 3 — Pitch statistics
        pitch_mean = float(np.mean(f0_voiced))
        pitch_std = float(np.std(f0_voiced))
        pitch_cv = pitch_std / pitch_mean if pitch_mean > 0 else 0.0

        # Semitone range
        f0_st = _hz_to_semitones(f0_voiced)
        range_st = float(np.max(f0_st) - np.min(f0_st))

        # 4 — Monotone detection
        is_monotone = pitch_cv < self._monotone_threshold

        # 5 — Sub-scores
        variance_score = _compute_variance_score(pitch_cv, self._monotone_threshold, self._cv_upper)
        range_score = _compute_range_score(range_st)
        contour_score = _compute_contour_score(f0_voiced)

        # Intonation composite: same relative proportions as the old 3-component
        # formula (50:30:20) but now they fill 55% of the overall prosody score.
        #   Within-intonation weights: 50/100, 30/100, 20/100 (unchanged)
        intonation_score = (
            0.50 * variance_score + 0.30 * range_score + 0.20 * contour_score
        )

        # Speed sub-score: how close the speech rate is to native-like rate.
        # Defaults to 50 (neutral) when word_durations are not available.
        if word_durations is not None and len(word_durations) > 0:
            speed_score = _compute_speed_score(word_durations, total_duration)
        else:
            speed_score = 50.0

        # Rhythm sub-score: nPVI — durational contrast between successive words.
        # Defaults to 50 (neutral) when word_durations are not available.
        if word_durations is not None and len(word_durations) > 0:
            rhythm_score = _compute_rhythm_score(word_durations)
        else:
            rhythm_score = 50.0

        # Weighted combination:
        #   55% intonation (pitch variance + range + contour)
        #   20% speed (speaking rate deviation from ideal)
        #   25% rhythm (nPVI — stress-timing naturalness)
        prosody_score = round(
            0.55 * intonation_score + 0.20 * speed_score + 0.25 * rhythm_score,
            2,
        )

        # Monotone cap — even if range/contour are okay, monotone speech
        # should not score above 30.  Azure penalises monotone heavily.
        if is_monotone:
            prosody_score = min(prosody_score, 30.0)

        prosody_score = min(max(prosody_score, 0.0), 100.0)

        logger.debug(
            "Prosody: mean={:.1f}Hz  std={:.1f}Hz  CV={:.3f}  "
            "range={:.1f}st  monotone={}  intonation={:.1f}  "
            "speed={:.1f}  rhythm={:.1f}  score={:.1f}",
            pitch_mean, pitch_std, pitch_cv,
            range_st, is_monotone, intonation_score,
            speed_score, rhythm_score, prosody_score,
        )

        return ProsodyResult(
            pitch_mean_hz=round(pitch_mean, 2),
            pitch_std_hz=round(pitch_std, 2),
            pitch_range_semitones=round(range_st, 2),
            voiced_ratio=round(voiced_ratio, 4),
            is_monotone=is_monotone,
            prosody_score=prosody_score,
        )


@lru_cache
def get_prosody_service() -> ProsodyService:
    """Cached singleton for ProsodyService."""
    return ProsodyService()
