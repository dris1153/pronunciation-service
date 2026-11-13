"""Interim v2 -> v1-shaped response, used only by speechocean762_eval.py --api v2.

The real response builder lives in the v2 API (Phase 05).
"""
from __future__ import annotations

from app.services.phoneme_align import _phoneme_similarity
from app.services.v2.gop_features import V2Analysis
from app.services.v2.scorer import Scores


def to_interim_response(analysis: V2Analysis, scores: Scores, mdd_threshold: float) -> dict:
    word_details = []
    for w, phone_scores, word_score in zip(analysis.words, scores.phone, scores.word):
        phones = []
        for ph, phone_score in zip(w.phones, phone_scores):
            sim = _phoneme_similarity(ph.expected, ph.heard) if ph.heard else 0.0
            phones.append({
                "expected_ipa": ph.expected,
                "actual_ipa": ph.heard,
                "gop_score": round(phone_score * 50, 2),
                "is_flagged": phone_score < mdd_threshold,
                "confidence_ipa": sim,
                "is_correct_ipa": ph.heard == ph.expected,
                "is_correct_lenient": sim > 0,
                "lpp": round(ph.lpp, 4),
                "features": [round(float(x), 4) for x in ph.features],
                "start_frame": ph.start,
                "end_frame": ph.end,
            })
        phones += [
            {"expected_ipa": "", "actual_ipa": a, "gop_score": 0.0, "confidence_ipa": 0.0,
             "is_correct_ipa": False}
            for a in w.inserted
        ]
        scored = [p for p in phones if p["expected_ipa"]]
        word_details.append({
            "word": w.word,
            "ipa_accuracy": round(100 * sum(p["is_correct_ipa"] for p in scored) / max(1, len(scored)), 2),
            "word_gop_score": round(word_score * 10, 2),
            "phoneme_details": phones,
            "start_frame": w.start,
            "end_frame": w.end,
        })
    return {
        "overall_score": round(scores.utt["total"] * 10, 2),
        "accuracy_score": round(scores.utt["accuracy"] * 10, 2),
        "completeness_score": round(scores.completeness * 10, 2),
        "fluency_score": round(scores.utt["fluency"] * 10, 2),
        "prosody_score": round(scores.utt["prosodic"] * 10, 2),
        "results": {"word_details": word_details},
    }
