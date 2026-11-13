"""IPA phoneme similarity groups and similarity-weighted DP alignment.

Torch-free so both v1 and the v2 runtime share one implementation.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from loguru import logger

# ── Phoneme similarity (for confidence scoring) ─────────────────────────────

# IPA phonemes grouped by phonetic class.  Phonemes in the same group are
# considered "similar" and receive a partial-confidence score on mismatch.
_PHONEME_GROUPS: list[set[str]] = [
    # Front vowels
    {"i", "ɪ", "eɪ", "ɛ", "æ"},
    # Central / open vowels
    {"ʌ", "ə", "ɑ", "ɚ", "ɝ"},
    # Back / rounded vowels
    {"u", "ʊ", "oʊ", "ɔ"},
    # Diphthongs
    {"aɪ", "aʊ", "ɔɪ"},
    # Plosives (voiceless)
    {"p", "t", "k"},
    # Plosives (voiced)
    {"b", "d", "ɡ"},
    # Fricatives (voiceless)
    {"f", "θ", "s", "ʃ", "h"},
    # Fricatives (voiced)
    {"v", "ð", "z", "ʒ"},
    # Affricates
    {"tʃ", "dʒ"},
    # Nasals
    {"m", "n", "ŋ"},
    # Approximants / glides
    {"l", "ɹ", "w", "j"},
]

# Pre-compute lookup: phoneme → group index
_PHONEME_TO_GROUP: dict[str, int] = {}
for _idx, _grp in enumerate(_PHONEME_GROUPS):
    for _ph in _grp:
        _PHONEME_TO_GROUP[_ph] = _idx


def _phoneme_similarity(a: str, b: str) -> float:
    """Return a similarity score in [0, 1] between two IPA phonemes.

    - 1.0  → exact match
    - 0.3  → same phonetic group (e.g. ɛ ↔ æ, both front vowels)
    - 0.0  → different groups or unknown

    Note: the partial credit for same-group phonemes is kept intentionally
    low (0.3).  A higher value (e.g. 0.6) inflates accuracy scores for
    non-native speakers who systematically substitute similar phonemes,
    causing large discrepancies vs Azure's stricter scoring.
    """
    if a == b:
        return 1.0
    ga = _PHONEME_TO_GROUP.get(a)
    gb = _PHONEME_TO_GROUP.get(b)
    if ga is not None and ga == gb:
        return 0.3
    return 0.0


# ── Sequence alignment (Levenshtein DP) ─────────────────────────────────────

# Alignment operation types
_MATCH = "match"            # phonemes are equal
_SUBSTITUTE = "substitute"  # phoneme differs
_INSERT = "insert"          # extra token in actual (not in reference)
_DELETE = "delete"          # missing token in actual (expected but absent)

# Epsilon for floating-point comparisons in back-trace
_EPS = 1e-6

# Safety cap for phoneme-level DP alignment.  Typical English words have
# 2–10 phonemes; 200 is extremely generous and prevents O(n*m) blow-up
# from malformed g2p output.
_MAX_ALIGN_PHONEMES = 200


def _align_phonemes(
    ref: Sequence[str],
    act: Sequence[str],
    max_phonemes: int = _MAX_ALIGN_PHONEMES,
) -> list[tuple[str, str, str]]:
    """Align two IPA phoneme sequences using Levenshtein DP with phonetic
    similarity costs.

    Returns a list of ``(operation, ref_phoneme, act_phoneme)`` triples.
    - match:      (match,      rp, ap)   — rp == ap
    - substitute: (substitute, rp, ap)   — rp != ap
    - delete:     (delete,     rp, "")   — missing in actual
    - insert:     (insert,     "",  ap)  — extra in actual
    """
    n, m = len(ref), len(act)

    # Guard: truncate excessively long phoneme sequences.
    if n > max_phonemes:
        logger.warning(
            "Ref phonemes truncated from {} to {} for DP alignment",
            n, max_phonemes,
        )
        ref = ref[:max_phonemes]
        n = max_phonemes
    if m > max_phonemes:
        logger.warning(
            "Act phonemes truncated from {} to {} for DP alignment",
            m, max_phonemes,
        )
        act = act[:max_phonemes]
        m = max_phonemes

    # Cost matrix (n+1) × (m+1) — use float64 for precision
    dp = np.zeros((n + 1, m + 1), dtype=np.float64)
    for i in range(1, n + 1):
        dp[i][0] = float(i)   # deletions
    for j in range(1, m + 1):
        dp[0][j] = float(j)   # insertions

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == act[j - 1]:
                cost_sub = 0.0
            else:
                # Cheaper substitution if phonemes share a phonetic group,
                # but only slightly — a substitution is still an error.
                cost_sub = 0.85 if _phoneme_similarity(ref[i - 1], act[j - 1]) > 0 else 1.0
            dp[i][j] = min(
                dp[i - 1][j] + 1.0,            # delete
                dp[i][j - 1] + 1.0,             # insert
                dp[i - 1][j - 1] + cost_sub,    # match / substitute
            )

    # Back-trace to recover the alignment path.
    # Use epsilon comparison to avoid float == float pitfalls with 0.85 costs.
    ops: list[tuple[str, str, str]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            cost_sub = 0.0 if ref[i - 1] == act[j - 1] else (
                0.85 if _phoneme_similarity(ref[i - 1], act[j - 1]) > 0 else 1.0
            )
            diag = dp[i - 1][j - 1] + cost_sub
            up   = dp[i - 1][j] + 1.0
            best = dp[i][j]

            # Prefer diagonal (match/substitute) → up (delete) → left (insert)
            if abs(best - diag) < _EPS:
                rp, ap = ref[i - 1], act[j - 1]
                op = _MATCH if rp == ap else _SUBSTITUTE
                ops.append((op, rp, ap))
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
