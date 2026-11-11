"""Score speechocean762 with the in-process pipeline and correlate with experts.

Dataset: https://www.openslr.org/101/ (CC BY 4.0). Extract to data/speechocean762.

Usage:
    # Run (resumable — scored utterances in --out are skipped, errors retried),
    # then report. Use one --out file per split: the report reads all of it.
    python scripts/speechocean762_eval.py --out data/so762-test.jsonl \
        --report reports/so762-test-report.json [--limit 200]

    # Recompute the report from an existing JSONL without running the model
    python scripts/speechocean762_eval.py --out ... --report ... --report-only

Calls PronunciationService._evaluate_sync directly: no HTTP, no rate limit,
no API key. Model and settings come from the environment / .env as usual.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from speechocean762_metrics import build_report  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--data-dir", type=Path, default=ROOT / "data" / "speechocean762")
    p.add_argument("--split", default="test", choices=["train", "test"])
    p.add_argument("--out", type=Path, required=True, help="JSONL predictions (appended)")
    p.add_argument("--report", type=Path, required=True, help="JSON metrics report")
    p.add_argument("--limit", type=int, default=0, help="Max utterances (0 = all)")
    p.add_argument("--report-only", action="store_true")
    return p.parse_args()


def _read_kv(path: Path) -> dict[str, str]:
    """Read a Kaldi-style ``<key><whitespace><value>`` file."""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            out[parts[0]] = parts[1].strip()
    return out


def load_split(data_dir: Path, split: str) -> list[tuple[str, Path, str, dict]]:
    """Return ``(utt_id, wav_path, text, human_scores)`` for every utterance.

    ``human_scores`` gets an extra ``age`` key (speaker age) for subset reports.
    """
    wavs = _read_kv(data_dir / split / "wav.scp")
    texts = _read_kv(data_dir / split / "text")
    utt2spk = _read_kv(data_dir / split / "utt2spk")
    spk2age = _read_kv(data_dir / split / "spk2age")
    scores = json.loads((data_dir / "resource" / "scores.json").read_text(encoding="utf-8"))
    return [
        (utt, data_dir / wav, texts[utt], {**scores[utt], "age": int(spk2age[utt2spk[utt]])})
        for utt, wav in sorted(wavs.items())
        if utt in texts and utt in scores
    ]


def _read_rows(path: Path) -> list[dict]:
    """Rows keyed by utt_id — a later line (e.g. a retry) replaces an earlier one."""
    if not path.exists():
        return []
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:  # truncated last line after a hard kill
            continue
        rows[row["utt_id"]] = row
    return list(rows.values())


def run(args: argparse.Namespace) -> None:
    from loguru import logger

    from app.services.pronunciation_service import get_pronunciation_service

    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    utts = load_split(args.data_dir, args.split)
    if args.limit:
        utts = utts[: args.limit]
    done = {r["utt_id"] for r in _read_rows(args.out) if "pred" in r}  # errors are retried
    todo = [u for u in utts if u[0] not in done]
    print(f"{len(utts)} utterances, {len(done)} already scored, {len(todo)} to run")

    svc = get_pronunciation_service()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    with args.out.open("a", encoding="utf-8") as fh:
        for i, (utt, wav, text, human) in enumerate(todo, 1):
            row: dict = {"utt_id": utt, "text": text, "human": human}
            try:
                row["pred"] = svc._evaluate_sync(wav.read_bytes(), text).model_dump(mode="json")
            except Exception as exc:  # noqa: BLE001 — record and keep going
                row["error"] = f"{type(exc).__name__}: {exc}"
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 100 == 0 or i == len(todo):
                rate = i / (time.perf_counter() - start)
                print(f"  {i}/{len(todo)}  {rate:.2f} utt/s")


def main() -> None:
    args = _parse_args()
    if not args.report_only:
        run(args)
    rows = _read_rows(args.out)
    report = {
        "all": build_report(rows),
        "adults_18plus": build_report([r for r in rows if r["human"].get("age", 0) >= 18]),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    failed = [r for r in rows if "error" in r]
    for r in failed[:10]:
        print(f"FAILED {r['utt_id']}: {r['error']}")


if __name__ == "__main__":
    main()
