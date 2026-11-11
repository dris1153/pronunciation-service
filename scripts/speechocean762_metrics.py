"""Correlation metrics between service output and speechocean762 expert scores.

Pure functions over the JSONL rows written by ``speechocean762_eval.py``:
``{"utt_id", "text", "human": <scores.json entry>, "pred": <PronunciationResponse>}``.

Human scales: utterance 0-10, word accuracy 0-10, phone accuracy 0-2. Pearson
correlation is scale-invariant, so nothing is rescaled.
"""
from __future__ import annotations

import math

import numpy as np

# speechocean762 utterance field -> PronunciationResponse field
UTT_FIELDS: dict[str, str] = {
    "accuracy": "accuracy_score",
    "completeness": "completeness_score",
    "fluency": "fluency_score",
    "prosodic": "prosody_score",
    "total": "overall_score",
}

# Phone scored below this (0-2 scale, averaged over experts) counts as mispronounced.
MISPRONOUNCED_BELOW = 1.0


def pcc(x: list[float], y: list[float]) -> float | None:
    """Pearson correlation; ``None`` when undefined (n < 2 or a constant series)."""
    if len(x) < 2 or len(x) != len(y):
        return None
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if xa.std() == 0 or ya.std() == 0:
        return None
    r = float(np.corrcoef(xa, ya)[0, 1])
    return None if math.isnan(r) else round(r, 4)


def pair_words(human: dict, pred: dict) -> list[tuple[dict, dict]]:
    """Pair human and predicted words by position; empty when counts differ."""
    h_words = human.get("words", [])
    p_words = pred["results"]["word_details"]
    if len(h_words) != len(p_words):
        return []
    return list(zip(h_words, p_words))


def pair_phones(h_word: dict, p_word: dict) -> list[tuple[float, dict]]:
    """Pair human phone scores with predicted reference-side phonemes by position.

    Inserted phonemes (``expected_ipa == ""``) have no human counterpart and are
    dropped. Returns ``[]`` when the phone counts differ (lexicon mismatch).
    """
    h_scores = h_word.get("phones-accuracy", [])
    p_phones = [p for p in p_word["phoneme_details"] if p["expected_ipa"]]
    if len(h_scores) != len(p_phones):
        return []
    return list(zip(h_scores, p_phones))


def mdd_prf(pairs: list[tuple[bool, bool]]) -> dict[str, float | None]:
    """Precision/recall/F1 for (human_wrong, predicted_wrong) pairs."""
    tp = sum(1 for h, p in pairs if h and p)
    fp = sum(1 for h, p in pairs if not h and p)
    fn = sum(1 for h, p in pairs if h and not p)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None
    return {
        "precision": None if precision is None else round(precision, 4),
        "recall": None if recall is None else round(recall, 4),
        "f1": None if f1 is None else round(f1, 4),
        "human_wrong": tp + fn,
        "n": len(pairs),
    }


def build_report(rows: list[dict]) -> dict:
    """Aggregate all metrics over successfully evaluated rows."""
    ok = [r for r in rows if "pred" in r]
    utt = {
        h: pcc([r["human"][h] for r in ok], [r["pred"][p] for r in ok])
        for h, p in UTT_FIELDS.items()
    }

    word_h, word_ipa, word_gop = [], [], []
    ph_h, ph_gop, ph_conf, mdd = [], [], [], []
    n_human_words = n_human_phones = 0
    for r in ok:
        n_human_words += len(r["human"].get("words", []))
        n_human_phones += sum(len(w.get("phones-accuracy", [])) for w in r["human"].get("words", []))
        for h_w, p_w in pair_words(r["human"], r["pred"]):
            word_h.append(h_w["accuracy"])
            word_ipa.append(p_w["ipa_accuracy"])
            word_gop.append(p_w["word_gop_score"])
            for h_score, p_ph in pair_phones(h_w, p_w):
                ph_h.append(h_score)
                ph_gop.append(p_ph["gop_score"])
                ph_conf.append(p_ph["confidence_ipa"])
                mdd.append((h_score < MISPRONOUNCED_BELOW, not p_ph["is_correct_ipa"]))

    return {
        "n_rows": len(rows),
        "n_ok": len(ok),
        "n_failed": len(rows) - len(ok),
        "utterance_pcc": utt,
        "word_pcc": {"ipa_accuracy": pcc(word_h, word_ipa), "word_gop_score": pcc(word_h, word_gop)},
        "word_coverage": round(len(word_h) / n_human_words, 4) if n_human_words else None,
        "phone_pcc": {"gop_score": pcc(ph_h, ph_gop), "confidence_ipa": pcc(ph_h, ph_conf)},
        "phone_coverage": round(len(ph_h) / n_human_phones, 4) if n_human_phones else None,
        "mdd": mdd_prf(mdd),
    }
