"""Learned scorer: GOP features -> phone / word / utterance scores (numpy, torch-free).

A small MLP gives phone scores (0-2); ridge heads on top give word and utterance scores. Phone scores feed word features (0-10), which feed the utterance heads (0-10).
Weights are trained on speechocean762 by ``training/train_scorer.py``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.services.ipa_service import _ARPABET_TO_IPA
from app.services.phoneme_align import _phoneme_similarity
from app.services.v2.gop_features import V2Analysis, WordAnalysis
from app.services.v2.phone_model import FRAME_MS

PHONES: list[str] = sorted(set(_ARPABET_TO_IPA.values()))
_PHONE_IDX = {p: i for i, p in enumerate(PHONES)}
# rare-phone one-hots have tiny variance; unclipped z-scores reach ~200
Z_CLIP = 10.0
UTT_TARGETS = ("accuracy", "fluency", "prosodic", "total")


@dataclass
class Linear:
    mean: np.ndarray
    std: np.ndarray
    w: np.ndarray
    b: float

    def predict(self, x: np.ndarray) -> np.ndarray:
        return ((x - self.mean) / self.std) @ self.w + self.b

    def to_json(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist(), "w": self.w.tolist(), "b": self.b}

    @classmethod
    def from_json(cls, d: dict) -> Linear:
        return cls(np.array(d["mean"]), np.array(d["std"]), np.array(d["w"]), float(d["b"]))


@dataclass
class Mlp:
    """Standardise -> (Linear, ReLU)* -> Linear; dropout is training-only."""

    mean: np.ndarray
    std: np.ndarray
    layers: list[tuple[np.ndarray, np.ndarray]]  # (W (in, out), b)

    def predict(self, x: np.ndarray) -> np.ndarray:
        h = np.clip((x - self.mean) / self.std, -Z_CLIP, Z_CLIP)
        for w, b in self.layers[:-1]:
            h = np.maximum(h @ w + b, 0.0)
        w, b = self.layers[-1]
        return (h @ w + b)[..., 0]

    def to_json(self) -> dict:
        return {"mean": self.mean.tolist(), "std": self.std.tolist(),
                "layers": [[w.tolist(), b.tolist()] for w, b in self.layers]}

    @classmethod
    def from_json(cls, d: dict) -> Mlp:
        return cls(np.array(d["mean"]), np.array(d["std"]), [(np.array(w), np.array(b)) for w, b in d["layers"]])


@dataclass
class Scores:
    phone: list[list[float]]  # per word, 0-2
    word: list[float]  # 0-10
    utt: dict[str, float]  # accuracy, fluency, prosodic, total: 0-10
    completeness: float  # 0-10


def phone_features(analysis: V2Analysis) -> list[np.ndarray]:
    """Per word: (n_phones, F) matrix."""
    out = []
    for w in analysis.words:
        lpps = np.array([p.lpp for p in w.phones])
        rows = []
        for i, p in enumerate(w.phones):
            sim = _phoneme_similarity(p.expected, p.heard) if p.heard else 0.0
            onehot = np.zeros(len(PHONES))
            onehot[_PHONE_IDX[p.expected]] = 1.0
            rows.append(np.concatenate([
                p.features, [np.exp(p.lpp), max(p.lpp, -10.0)], onehot,
                [p.heard == "", p.heard not in ("", p.expected) and sim > 0, p.heard not in ("", p.expected) and sim == 0],
                [lpps[i - 1] if i else 0.0, lpps[i + 1] if i + 1 < len(lpps) else 0.0, lpps.mean(), lpps.min()],
            ]))
        out.append(np.array(rows, dtype=float).reshape(len(rows), -1))
    return out


def word_features(w: WordAnalysis, phone_pred: list[float]) -> np.ndarray:
    n = max(1, len(w.phones))
    p = np.array(phone_pred) if phone_pred else np.zeros(1)
    lpp = np.array([ph.lpp for ph in w.phones]) if w.phones else np.zeros(1)
    deleted = sum(ph.heard == "" for ph in w.phones)
    wrong = sum(ph.heard != ph.expected for ph in w.phones)
    return np.array([
        p.mean(), p.min(), p.max(), p.std(), lpp.mean(), lpp.min(), len(w.phones),
        deleted / n, wrong / n, len(w.inserted), (w.end - w.start) * FRAME_MS / 1000,
    ])


def utt_features(a: V2Analysis, phone_pred: list[list[float]], word_pred: list[float]) -> np.ndarray:
    flat = np.array([x for ps in phone_pred for x in ps]) if any(phone_pred) else np.zeros(1)
    phones = [p for w in a.words for p in w.phones]
    n = max(1, len(phones))
    wp = np.array(word_pred) if word_pred else np.zeros(1)
    starts = [w.start for w in a.words if w.phones]
    ends = [w.end for w in a.words if w.phones]
    dur = max(0.1, (max(ends) - min(starts)) * FRAME_MS / 1000) if starts else 0.1
    gaps = np.array([(s - e) * FRAME_MS / 1000 for s, e in zip(starts[1:], ends[:-1])]) if len(starts) > 1 else np.zeros(1)
    return np.array([
        flat.mean(), flat.min(), flat.std(), (flat < 1).mean(), wp.mean(), wp.min(), wp.std(),
        np.mean([p.lpp for p in phones]) if phones else 0.0,
        sum(p.heard != p.expected for p in phones) / n, sum(p.heard == "" for p in phones) / n,
        sum(len(w.inserted) for w in a.words) / n,
        len(phones) / dur, dur, gaps.mean(), gaps.max(), gaps.sum() / dur, len(a.words),
    ])


class Scorer:
    def __init__(self, phone: Mlp, word: Linear, utt: dict[str, Linear], mdd_threshold: float) -> None:
        self.phone, self.word, self.utt = phone, word, utt
        self.mdd_threshold = mdd_threshold  # phone score below this = mispronounced

    @classmethod
    def load(cls, path: Path) -> Scorer:
        d = json.loads(path.read_text(encoding="utf-8"))
        return cls(Mlp.from_json(d["phone"]), Linear.from_json(d["word"]),
                   {k: Linear.from_json(v) for k, v in d["utt"].items()}, d["mdd_threshold"])

    def score(self, a: V2Analysis) -> Scores:
        phone = [np.clip(self.phone.predict(m), 0, 2).tolist() if len(m) else [] for m in phone_features(a)]
        word = [float(np.clip(self.word.predict(word_features(w, p)), 0, 10)) for w, p in zip(a.words, phone)]
        x = utt_features(a, phone, word)
        utt = {k: float(np.clip(m.predict(x), 0, 10)) for k, m in self.utt.items()}
        phones = [p for w in a.words for p in w.phones]
        completeness = 10.0 * (1 - sum(p.heard == "" for p in phones) / max(1, len(phones)))
        return Scores(phone, word, utt, completeness)
