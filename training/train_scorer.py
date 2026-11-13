"""Fit the v2 ridge scorer on speechocean762 train features, report on test.

    python -m training.train_scorer --train data/so762-v2-train.jsonl --test data/so762-v2-test.jsonl

Inputs are the JSONL files written by ``scripts/speechocean762_eval.py --api v2``.
Phone -> word -> utterance models are stacked with speaker-grouped out-of-fold predictions.
"""
from __future__ import annotations

import argparse
import json
import sys
import zlib
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from speechocean762_eval import _read_kv, _read_rows  # noqa: E402

from app.services.v2.gop_features import PhoneAnalysis, V2Analysis, WordAnalysis  # noqa: E402
from app.services.v2.scorer import (  # noqa: E402
    UTT_TARGETS, Linear, Mlp, phone_features, utt_features, word_features,
)
from training.scorer_mlp import fit_mlp  # noqa: E402

FOLDS = 5
LAMBDAS = (1.0, 10.0, 100.0, 1000.0)


def to_analysis(pred: dict) -> V2Analysis:
    words = []
    for w in pred["results"]["word_details"]:
        phones = [
            PhoneAnalysis(p["expected_ipa"], p["actual_ipa"], p["start_frame"], p["end_frame"],
                          lpp=p["lpp"], features=np.array(p["features"]))
            for p in w["phoneme_details"] if p["expected_ipa"]
        ]
        ins = [p["actual_ipa"] for p in w["phoneme_details"] if not p["expected_ipa"]]
        words.append(WordAnalysis(w["word"], phones, ins))
    return V2Analysis(words, [], 0)


def load(path: Path, split: str, data_dir: Path) -> list[dict]:
    """Rows with analysis, human scores and speaker id."""
    spk = _read_kv(data_dir / split / "utt2spk")
    out = []
    for r in _read_rows(path):
        if "pred" not in r:
            continue
        a, h = to_analysis(r["pred"]), r["human"]
        if len(h["words"]) == len(a.words):
            ok = [len(hw["phones-accuracy"]) == len(aw.phones) for hw, aw in zip(h["words"], a.words)]
        else:
            ok = [False] * len(a.words)
        out.append({"a": a, "h": h, "spk": spk[r["utt_id"]], "ok": ok, "age": h["age"]})
    return out


def fit_ridge(x: np.ndarray, y: np.ndarray, lam: float) -> Linear:
    mean, std = x.mean(0), np.maximum(x.std(0), 1e-6)
    z = (x - mean) / std
    ym = y.mean()
    w = np.linalg.solve(z.T @ z + lam * np.eye(z.shape[1]), z.T @ (y - ym))
    return Linear(mean, std, w, float(ym))


def oof_fit(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[Linear, np.ndarray, float]:
    """Pick lambda by speaker-grouped CV; return the full-data model and OOF predictions."""
    fold = np.array([zlib.crc32(g.encode()) % FOLDS for g in groups])
    best_r, best_lam, best_pred = -2.0, 0.0, None
    for lam in LAMBDAS:
        pred = np.zeros(len(y))
        for f in range(FOLDS):
            pred[fold == f] = fit_ridge(x[fold != f], y[fold != f], lam).predict(x[fold == f])
        r = np.corrcoef(pred, y)[0, 1]
        if r > best_r:
            best_r, best_lam, best_pred = r, lam, pred
    return fit_ridge(x, y, best_lam), best_pred, best_lam


def oof_mlp(x: np.ndarray, y: np.ndarray, groups: np.ndarray) -> tuple[Mlp, np.ndarray]:
    """Full-data MLP plus speaker-grouped OOF predictions (for stacking)."""
    fold = np.array([zlib.crc32(g.encode()) % FOLDS for g in groups])
    pred = np.zeros(len(y))
    for f in range(FOLDS):
        pred[fold == f] = fit_mlp(x[fold != f], y[fold != f], groups[fold != f]).predict(x[fold == f])
    return fit_mlp(x, y, groups), pred


def pcc(a, b) -> float:
    return round(float(np.corrcoef(a, b)[0, 1]), 4)


def prf(pred: np.ndarray, wrong: np.ndarray, thr: float) -> tuple[float, float, float]:
    flag = pred < thr
    tp = int((flag & wrong).sum())
    return (round(tp / max(1, flag.sum()), 4), round(tp / max(1, wrong.sum()), 4),
            round(2 * tp / max(1, flag.sum() + wrong.sum()), 4))


def phone_table(rows: list[dict]):
    """Feature matrix, human phone scores and (utt, word) index for every labelled phone."""
    X, y, idx = [], [], []
    for ui, r in enumerate(rows):
        for wi, m in enumerate(phone_features(r["a"])):
            if r["ok"][wi]:
                X.append(m)
                y += r["h"]["words"][wi]["phones-accuracy"]
                idx += [(ui, wi)] * len(m)
    return np.vstack(X), np.array(y), idx


def predict_phones(model: Mlp, row: dict) -> list[list[float]]:
    return [np.clip(model.predict(m), 0, 2).tolist() if len(m) else [] for m in phone_features(row["a"])]


def word_table(rows, phone_pred):
    X, y, groups = [], [], []
    for r, pp in zip(rows, phone_pred):
        for wi, w in enumerate(r["a"].words):
            if r["ok"][wi]:
                X.append(word_features(w, pp[wi]))
                y.append(r["h"]["words"][wi]["accuracy"])
                groups.append(r["spk"])
    return np.array(X), np.array(y, dtype=float), np.array(groups)


def word_preds(model: Linear, rows, phone_pred):
    return [[float(np.clip(model.predict(word_features(w, pp[wi])), 0, 10)) for wi, w in enumerate(r["a"].words)]
            for r, pp in zip(rows, phone_pred)]


def utt_table(rows, phone_pred, word_pred):
    return np.array([utt_features(r["a"], pp, wp) for r, pp, wp in zip(rows, phone_pred, word_pred)])


def report(te, sel, te_phone, te_word, utt_m, Xt, thr) -> dict:
    rep = {t: pcc(utt_m[t].predict(Xt[sel]), [r["h"][t] for r, s in zip(te, sel) if s]) for t in UTT_TARGETS}
    ph_h, ph_p, w_h, w_p = [], [], [], []
    for r, pp, wp, s in zip(te, te_phone, te_word, sel):
        if not s:
            continue
        for wi, ok in enumerate(r["ok"]):
            if ok:
                ph_h += r["h"]["words"][wi]["phones-accuracy"]
                ph_p += pp[wi]
                w_h.append(r["h"]["words"][wi]["accuracy"])
                w_p.append(wp[wi])
    ph_h, ph_p = np.array(ph_h), np.array(ph_p)
    return rep | {"phone": pcc(ph_h, ph_p), "word": pcc(w_h, w_p), "mdd_p_r_f1": prf(ph_p, ph_h < 1.0, thr)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--train", type=Path, default=ROOT / "data" / "so762-v2-train.jsonl")
    ap.add_argument("--test", type=Path, default=ROOT / "data" / "so762-v2-test.jsonl")
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data" / "speechocean762")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "models" / "hubert-phone-ctc" / "scorer.json")
    args = ap.parse_args()
    tr, te = load(args.train, "train", args.data_dir), load(args.test, "test", args.data_dir)
    print(f"train {len(tr)} utts, test {len(te)} utts")

    X, y, idx = phone_table(tr)
    phone_m, phone_oof = oof_mlp(X, y, np.array([tr[u]["spk"] for u, _ in idx]))
    print(f"phone MLP OOF PCC={pcc(phone_oof, y):.4f}")
    oof_by_word: dict[tuple[int, int], list[float]] = {}
    for key, p in zip(idx, np.clip(phone_oof, 0, 2)):
        oof_by_word.setdefault(key, []).append(float(p))
    tr_phone = []
    for u, r in enumerate(tr):
        full = None
        per_word = []
        for wi in range(len(r["a"].words)):
            if (u, wi) not in oof_by_word and full is None:
                full = predict_phones(phone_m, r)
            per_word.append(oof_by_word.get((u, wi)) or full[wi])
        tr_phone.append(per_word)
    # F1-optimal flag threshold on OOF predictions vs human phone score < 1
    thr = max(np.arange(0.5, 1.9, 0.02), key=lambda t: prf(phone_oof, y < 1.0, t)[2])

    Xw, yw, gw = word_table(tr, tr_phone)
    word_m, word_oof, lam = oof_fit(Xw, yw, gw)
    print(f"word ridge lambda={lam} OOF PCC={pcc(word_oof, yw):.4f}")
    tr_word = word_preds(word_m, tr, tr_phone)

    Xu, gu = utt_table(tr, tr_phone, tr_word), np.array([r["spk"] for r in tr])
    utt_m = {}
    for t in UTT_TARGETS:
        yt = np.array([r["h"][t] for r in tr], dtype=float)
        utt_m[t], oof, lam = oof_fit(Xu, yt, gu)
        print(f"utt {t} lambda={lam} OOF PCC={pcc(oof, yt):.4f}")

    args.out.write_text(json.dumps({
        "phone": phone_m.to_json(), "word": word_m.to_json(),
        "utt": {k: v.to_json() for k, v in utt_m.items()}, "mdd_threshold": float(thr),
    }), encoding="utf-8")
    print(f"mdd threshold {thr:.2f}; wrote {args.out}")

    te_phone = [predict_phones(phone_m, r) for r in te]
    te_word = word_preds(word_m, te, te_phone)
    Xt = utt_table(te, te_phone, te_word)
    for label, sel in (("all", np.ones(len(te), bool)), ("adults", np.array([r["age"] >= 18 for r in te]))):
        print(label, json.dumps(report(te, sel, te_phone, te_word, utt_m, Xt, thr)))


if __name__ == "__main__":
    main()
