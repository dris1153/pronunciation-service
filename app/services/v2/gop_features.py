"""GOP features per canonical phone and heard-phone diagnosis (torch-free)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from app.services.phoneme_align import _DELETE, _INSERT, _align_phonemes
from app.services.v2.ctc_align import forced_align

BLANK_ID = 0


@dataclass
class PhoneAnalysis:
    expected: str
    heard: str = ""  # "" = deleted
    start: int = 0  # token frames [start, end)
    end: int = 0
    timing_end: int = 0  # start of the next phone (or end): token + following blanks
    lpp: float = 0.0
    features: np.ndarray = field(default_factory=lambda: np.zeros(0))  # [LPP, LPR_1..LPR_n, log_dur]


@dataclass
class WordAnalysis:
    word: str
    phones: list[PhoneAnalysis]
    inserted: list[str] = field(default_factory=list)  # heard phones with no expected counterpart

    @property
    def start(self) -> int:
        return self.phones[0].start if self.phones else 0

    @property
    def end(self) -> int:
        return self.phones[-1].end if self.phones else 0


@dataclass
class V2Analysis:
    words: list[WordAnalysis]
    heard: list[str]
    n_frames: int


def greedy_decode(log_probs: np.ndarray) -> list[int]:
    """argmax, collapse repeats, drop blank."""
    ids = log_probs.argmax(axis=-1)
    keep = np.concatenate(([True], ids[1:] != ids[:-1])) & (ids != BLANK_ID)
    return ids[keep].tolist()


def phone_features(log_probs: np.ndarray, span: tuple[int, int], timing_end: int, phone_id: int) -> np.ndarray:
    mean = log_probs[span[0]:span[1]].mean(axis=0)
    lpp = mean[phone_id]
    log_dur = np.log(max(1, timing_end - span[0]))
    return np.concatenate(([lpp], lpp - mean[1:], [log_dur]))


def analyse_posteriors(
    log_probs: np.ndarray,
    words: list[tuple[str, list[str]]],
    vocab: list[str],
) -> V2Analysis:
    """``words`` = ``(word, canonical phones)``; phones outside ``vocab`` are dropped."""
    phone_to_id = {p: i for i, p in enumerate(vocab)}
    analysed = [
        WordAnalysis(w, [PhoneAnalysis(p) for p in phones if p in phone_to_id]) for w, phones in words
    ]
    flat = [(wi, ph) for wi, w in enumerate(analysed) for ph in w.phones]
    targets = [phone_to_id[ph.expected] for _, ph in flat]

    spans = forced_align(log_probs, targets, BLANK_ID)
    for k, ((_, ph), span) in enumerate(zip(flat, spans)):
        ph.start, ph.end = span
        ph.timing_end = spans[k + 1][0] if k + 1 < len(spans) else span[1]
        ph.features = phone_features(log_probs, span, ph.timing_end, targets[k])
        ph.lpp = float(ph.features[0])

    heard = [vocab[i] for i in greedy_decode(log_probs)]
    pos, last_word = 0, 0
    for op, _, act in _align_phonemes([ph.expected for _, ph in flat], heard):
        if op == _INSERT:
            analysed[last_word].inserted.append(act)
            continue
        last_word, ph = flat[pos]
        ph.heard = "" if op == _DELETE else act
        pos += 1
    return V2Analysis(analysed, heard, len(log_probs))
