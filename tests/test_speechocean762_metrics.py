"""Tests for scripts/speechocean762_metrics.py (no dataset needed)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from speechocean762_metrics import (  # noqa: E402
    build_report,
    mdd_prf,
    pair_phones,
    pair_words,
    pcc,
)


def _phone(expected: str, correct: bool, gop: float) -> dict:
    return {
        "expected_ipa": expected,
        "is_correct_ipa": correct,
        "confidence_ipa": 1.0 if correct else 0.0,
        "gop_score": gop,
    }


def _row(total: float, overall: float, phone_scores: list[float], correct: list[bool]) -> dict:
    phones = [_phone("p", c, 90.0 if c else 10.0) for c in correct]
    return {
        "utt_id": "u",
        "human": {
            "accuracy": total, "completeness": 10, "fluency": total,
            "prosodic": total, "total": total,
            "words": [{"accuracy": total, "phones-accuracy": phone_scores}],
        },
        "pred": {
            "accuracy_score": overall, "completeness_score": 100.0,
            "fluency_score": overall, "prosody_score": overall, "overall_score": overall,
            "results": {"word_details": [{
                "ipa_accuracy": overall, "word_gop_score": overall, "phoneme_details": phones,
            }]},
        },
    }


class TestPcc:
    def test_perfect_correlation(self):
        assert pcc([1, 2, 3], [10, 20, 30]) == 1.0

    def test_constant_series_is_none(self):
        assert pcc([5, 5, 5], [1, 2, 3]) is None

    def test_too_short_is_none(self):
        assert pcc([1], [1]) is None


class TestPairing:
    def test_word_count_mismatch_skips(self):
        human = {"words": [{}, {}]}
        pred = {"results": {"word_details": [{}]}}
        assert pair_words(human, pred) == []

    def test_inserted_phonemes_are_dropped(self):
        h_word = {"phones-accuracy": [2.0, 0.0]}
        p_word = {"phoneme_details": [
            _phone("a", True, 90), _phone("", False, 0), _phone("b", False, 10),
        ]}
        pairs = pair_phones(h_word, p_word)
        assert [h for h, _ in pairs] == [2.0, 0.0]
        assert [p["expected_ipa"] for _, p in pairs] == ["a", "b"]

    def test_phone_count_mismatch_skips(self):
        assert pair_phones({"phones-accuracy": [2.0]}, {"phoneme_details": []}) == []


class TestMdd:
    def test_prf(self):
        pairs = [(True, True), (True, False), (False, True), (False, False)]
        out = mdd_prf(pairs)
        assert out["precision"] == 0.5
        assert out["recall"] == 0.5
        assert out["f1"] == 0.5
        assert out["human_wrong"] == 2

    def test_no_predictions_gives_none(self):
        assert mdd_prf([(True, False)])["precision"] is None

    def test_all_misses_gives_zero_f1(self):
        out = mdd_prf([(True, False), (False, True)])
        assert out["precision"] == 0.0
        assert out["recall"] == 0.0
        assert out["f1"] == 0.0


class TestBuildReport:
    def test_end_to_end_and_failed_rows(self):
        rows = [
            _row(9, 90.0, [2.0, 2.0], [True, True]),
            _row(5, 50.0, [2.0, 0.0], [True, False]),
            _row(2, 20.0, [0.0, 0.0], [False, False]),
            {"utt_id": "bad", "error": "decode failed"},
        ]
        report = build_report(rows)
        assert report["n_ok"] == 3 and report["n_failed"] == 1
        assert report["utterance_pcc"]["total"] == 1.0
        assert report["utterance_pcc"]["completeness"] is None  # constant human score
        assert report["phone_coverage"] == 1.0
        assert report["mdd"]["f1"] == 1.0
