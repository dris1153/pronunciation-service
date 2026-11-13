"""CTC forced alignment (Viterbi) in numpy."""
from __future__ import annotations

import numpy as np

NEG = -1e30


def forced_align(log_probs: np.ndarray, targets: list[int], blank: int = 0) -> list[tuple[int, int]]:
    """Best CTC path for ``targets``; returns one ``(start, end)`` frame span
    (end exclusive) per target token.

    Raises ValueError when the audio is too short to emit the targets.
    """
    T, L = log_probs.shape[0], len(targets)
    if L == 0:
        return []
    repeats = sum(1 for a, b in zip(targets, targets[1:]) if a == b)
    if T < L + repeats:
        raise ValueError(f"{T} frames cannot align {L} tokens ({repeats} repeats)")

    S = 2 * L + 1
    labels = np.full(S, blank, dtype=np.int64)
    labels[1::2] = targets
    # state s may be entered from s-2 only if it is a token that differs from the token two back
    skip = np.zeros(S, dtype=bool)
    skip[3::2] = np.asarray(targets[1:]) != np.asarray(targets[:-1]) if L > 1 else False

    emit = log_probs[:, labels]  # (T, S)
    alpha = np.full(S, NEG)
    alpha[0], alpha[1] = emit[0, 0], emit[0, 1]
    back = np.zeros((T, S), dtype=np.int8)  # 0 stay, 1 from s-1, 2 from s-2
    for t in range(1, T):
        stay = alpha
        prev1 = np.concatenate(([NEG], alpha[:-1]))
        prev2 = np.where(skip, np.concatenate(([NEG, NEG], alpha[:-2])), NEG)
        stacked = np.stack([stay, prev1, prev2])
        choice = stacked.argmax(axis=0)
        back[t] = choice
        alpha = stacked[choice, np.arange(S)] + emit[t]

    s = S - 1 if alpha[S - 1] >= alpha[S - 2] else S - 2
    path = np.empty(T, dtype=np.int64)
    for t in range(T - 1, -1, -1):
        path[t] = s
        s -= back[t, s]

    spans: list[tuple[int, int]] = []
    for k in range(L):
        frames = np.flatnonzero(path == 2 * k + 1)
        spans.append((int(frames[0]), int(frames[-1]) + 1))
    return spans
