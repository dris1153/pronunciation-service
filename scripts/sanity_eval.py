"""Run the sanity dataset against a live service and report drift.

Phase 06 / Finding 15.

Usage:
    # Run + print table only
    python scripts/sanity_eval.py --api-key=$API_KEY

    # Save baseline (run once after a known-good deploy)
    python scripts/sanity_eval.py --api-key=$API_KEY --save-baseline=baseline.json

    # Compare against a baseline (CI / pre-deploy gate)
    python scripts/sanity_eval.py --api-key=$API_KEY --compare-baseline=baseline.json

Acceptance for `--compare-baseline`:
- Per-recording overall_score deviation < 5pt
- 0 quality-tier flips
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

DATASET = Path(__file__).resolve().parent.parent / "tests" / "sanity_dataset"


def run_sanity(api_url: str, api_key: str, timeout: float) -> dict:
    """Hit /api/v1/evaluate for every recording in the dataset."""
    if not DATASET.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {DATASET}. "
            f"Run scripts/generate_sanity_audio.py first."
        )

    results: dict[str, dict] = {}
    for rec_dir in sorted(DATASET.iterdir()):
        if not rec_dir.is_dir():
            continue
        audio = (rec_dir / "audio.wav").read_bytes()
        ref = (rec_dir / "reference.txt").read_text(encoding="utf-8").strip()
        expected = json.loads((rec_dir / "expected.json").read_text(encoding="utf-8"))

        headers = {"X-API-Key": api_key} if api_key else {}
        resp = httpx.post(
            f"{api_url.rstrip('/')}/api/v1/evaluate",
            files={"audio": ("a.wav", audio, "audio/wav")},
            data={"reference_text": ref},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        body = resp.json()

        results[rec_dir.name] = {
            "overall_score": float(body["overall_score"]),
            "level": body["level"],
            "expected_band": [expected["min_score"], expected["max_score"]],
            "in_band": expected["min_score"] <= body["overall_score"] <= expected["max_score"],
        }
    return results


def compare_baseline(current: dict, baseline_path: Path) -> tuple[bool, list[str]]:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for rec_id, cur in current.items():
        base = baseline.get(rec_id)
        if base is None:
            failures.append(f"{rec_id}: no baseline entry")
            continue
        deviation = abs(cur["overall_score"] - base["overall_score"])
        if deviation > 5.0:
            failures.append(
                f"{rec_id}: score deviation {deviation:.1f}pt > 5pt threshold "
                f"(was {base['overall_score']:.1f}, now {cur['overall_score']:.1f})"
            )
        if cur["level"] != base["level"]:
            failures.append(
                f"{rec_id}: quality tier flipped: {base['level']} → {cur['level']}"
            )
    return (len(failures) == 0), failures


def print_table(results: dict) -> None:
    print(f"{'recording':<28} {'score':<8} {'level':<10} {'band':<14} {'in band':<8}")
    print("-" * 70)
    for rec_id, r in results.items():
        band = f"[{r['expected_band'][0]},{r['expected_band'][1]}]"
        flag = "OK" if r["in_band"] else "FAIL"
        print(f"{rec_id:<28} {r['overall_score']:<8.1f} {r['level']:<10} {band:<14} {flag:<8}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api-url", default="http://localhost:8000")
    p.add_argument("--api-key", default="")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--save-baseline", type=Path, default=None)
    p.add_argument("--compare-baseline", type=Path, default=None)
    args = p.parse_args()

    results = run_sanity(args.api_url, args.api_key, args.timeout)
    print_table(results)

    if args.save_baseline:
        args.save_baseline.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nBaseline saved → {args.save_baseline}")

    if args.compare_baseline:
        ok, failures = compare_baseline(results, args.compare_baseline)
        if not ok:
            print("\n!! DRIFT DETECTED !!")
            for f in failures:
                print(f"  - {f}")
            sys.exit(1)
        print(f"\nNo drift vs {args.compare_baseline}")

    if not all(r["in_band"] for r in results.values()):
        print("\nFAIL: at least one recording out of expected band.")
        sys.exit(1)


if __name__ == "__main__":
    main()
