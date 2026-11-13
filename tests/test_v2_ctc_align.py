"""numpy CTC forced alignment must agree with torchaudio's reference implementation."""
import numpy as np
import pytest
import torch
import torchaudio.functional as taf

from app.services.v2.ctc_align import forced_align


def _random_log_probs(T: int, V: int, seed: int) -> np.ndarray:
    logits = np.random.default_rng(seed).normal(size=(T, V)) * 3
    logits -= logits.max(-1, keepdims=True)
    return logits - np.log(np.exp(logits).sum(-1, keepdims=True))


def _frame_path(spans: list[tuple[int, int]], targets: list[int], T: int) -> list[int]:
    path = [0] * T
    for (s, e), tok in zip(spans, targets):
        path[s:e] = [tok] * (e - s)
    return path


@pytest.mark.parametrize("targets", [
    [3, 5, 7, 9],
    [3, 3, 5],            # repeated token needs a blank between
    [4, 4, 4, 2, 2],
    [6],
])
@pytest.mark.parametrize("seed", range(5))
def test_parity_with_torchaudio(targets, seed):
    lp = _random_log_probs(40, 12, seed)
    spans = forced_align(lp, targets)
    ref, _ = taf.forced_align(torch.tensor(lp, dtype=torch.float32)[None], torch.tensor([targets], dtype=torch.int32))
    assert _frame_path(spans, targets, 40) == ref[0].tolist()


def test_tight_fit_has_no_blank_between_distinct_tokens():
    # T == L + repeats: [1,1,2] needs frames 1,blank,1,2
    lp = _random_log_probs(4, 5, 0)
    assert len(forced_align(lp, [1, 1, 2])) == 3


def test_too_short_raises():
    with pytest.raises(ValueError):
        forced_align(_random_log_probs(3, 5, 0), [1, 1, 2])


def test_empty_targets():
    assert forced_align(_random_log_probs(10, 5, 0), []) == []
