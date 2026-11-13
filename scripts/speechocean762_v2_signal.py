"""Signal check for the v2 phone model on speechocean762 (phone PCC, MDD, confusions, latency).

    python scripts/speechocean762_v2_signal.py data/so762-v2-test.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from speechocean762_metrics import MISPRONOUNCED_BELOW, mdd_prf, pair_phones, pair_words, pcc  # noqa: E402

# Vietnamese-learner staples: th/dh stopping, sibilant merging, affricate/fricative swaps
VN_PAIRS = {("θ", "t"), ("θ", "s"), ("ð", "d"), ("ð", "z"), ("ʃ", "s"), ("ʒ", "z"), ("tʃ", "ʃ"),
            ("dʒ", "z"), ("v", "b"), ("z", "s"), ("ɹ", "l")}


def _rows(path: Path, adults_only: bool) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if "pred" in r and (not adults_only or r["human"].get("age", 0) >= 18)]


def analyse(rows: list[dict]) -> dict:
    human, series = [], {"lpp": [], "min_lpr": [], "log_dur": []}
    strict, lenient, flagged, confusions = [], [], [], Counter()
    wrong_by_pair: Counter = Counter()
    for r in rows:
        for h_w, p_w in pair_words(r["human"], r["pred"]):
            for h_score, ph in pair_phones(h_w, p_w):
                f = ph["features"]
                human.append(h_score)
                series["lpp"].append(f[0])
                series["min_lpr"].append(min(f[1:-1]))
                series["log_dur"].append(f[-1])
                wrong = h_score < MISPRONOUNCED_BELOW
                strict.append((wrong, not ph["is_correct_ipa"]))
                lenient.append((wrong, not ph["is_correct_lenient"] and not ph["is_correct_ipa"]))
                flagged.append((wrong, ph["is_flagged"]))
                if not ph["is_correct_ipa"]:
                    pair = (ph["expected_ipa"], ph["actual_ipa"] or "∅")
                    confusions[pair] += 1
                    wrong_by_pair[pair] += wrong
    top = [
        {"expected": e, "heard": h, "n": n, "human_wrong_rate": round(wrong_by_pair[(e, h)] / n, 2),
         "vn_relevant": (e, h) in VN_PAIRS or h == "∅"}
        for (e, h), n in confusions.most_common(20)
    ]
    ms = [r["ms"] for r in rows if "ms" in r]
    return {
        "n_phones": len(human),
        "phone_pcc": {k: pcc(human, v) for k, v in series.items()},
        "mdd_strict": mdd_prf(strict),
        "mdd_lenient": mdd_prf(lenient),
        "mdd_scorer": mdd_prf(flagged),
        "top_confusions": top,
        "latency_ms": {"p50": float(np.percentile(ms, 50)), "p95": float(np.percentile(ms, 95))} if ms else None,
    }


if __name__ == "__main__":
    path = Path(sys.argv[1])
    print(json.dumps({"all": analyse(_rows(path, False)), "adults": analyse(_rows(path, True))},
                     indent=1, ensure_ascii=False))
