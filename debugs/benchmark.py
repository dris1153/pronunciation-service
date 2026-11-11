"""Per-stage latency benchmark for the /evaluate pipeline (in-process, real models).

Usage:
    python debugs/benchmark.py [--cpus 2] [--concurrency 1] [--runs 5]
                               [--dataset-dir tests/sanity_dataset]

Each sub-directory of --dataset-dir must hold ``audio.wav`` + ``reference.txt``
(generate the sanity set with ``scripts/generate_sanity_audio.py``).

--cpus pins the process to N cores, mimicking an N-vCPU VPS (Docker ``--cpus``
is not available on every dev box). --concurrency K runs K requests in parallel
threads, like K inference slots, and reports throughput. Torch threads default
to N // K like the app (app.core.concurrency.torch_threads_per_slot);
--threads T overrides that.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

os.environ.setdefault("DEBUG", "true")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
STAGES = ("decode", "asr", "ipa", "gop", "prosody")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--cpus", type=int, default=0, help="Pin to N cores (0 = no pinning)")
    p.add_argument(
        "--threads", type=int, default=0,
        help="Torch threads (0 = cpus // concurrency, like the app)",
    )
    p.add_argument("--concurrency", type=int, default=1)
    p.add_argument("--runs", type=int, default=5, help="Measured runs per sample")
    p.add_argument("--warmup", type=int, default=1)
    p.add_argument(
        "--dataset-dir", type=Path, default=ROOT / "tests" / "sanity_dataset"
    )
    return p.parse_args()


def _load_samples(dataset_dir: Path) -> list[tuple[str, bytes, str, float]]:
    import soundfile as sf

    samples = []
    for d in sorted(p for p in dataset_dir.iterdir() if p.is_dir()):
        wav, ref = d / "audio.wav", d / "reference.txt"
        if wav.exists() and ref.exists():
            info = sf.info(str(wav))
            samples.append(
                (d.name, wav.read_bytes(), ref.read_text(encoding="utf-8").strip(), info.duration)
            )
    if not samples:
        sys.exit(f"No audio.wav + reference.txt pairs under {dataset_dir}")
    return samples


def _p(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _row(label: str, timings: list[dict]) -> str:
    cells = [f"{statistics.median(t[s] for t in timings):.0f}" for s in STAGES]
    totals = [t["total"] for t in timings]
    return (
        f"| {label} | " + " | ".join(cells)
        + f" | {statistics.median(totals):.0f} | {_p(totals, 0.9):.0f} |"
    )


def main() -> None:
    args = _parse_args()
    import psutil

    proc = psutil.Process()
    if args.cpus:
        proc.cpu_affinity(list(range(args.cpus)))

    import torch

    threads = args.threads or (max(1, args.cpus // args.concurrency) if args.cpus else 0)
    if threads:
        torch.set_num_threads(threads)

    from loguru import logger

    from app.services.pronunciation_service import get_pronunciation_service

    timings: list[dict] = []
    logger.remove()
    logger.add(
        lambda m: timings.append(m.record["extra"]["stage_ms"]),
        filter=lambda r: r["message"] == "evaluate_timing",
    )

    t0 = time.perf_counter()
    svc = get_pronunciation_service()
    load_s = time.perf_counter() - t0
    rss_loaded = proc.memory_info().rss / 2**20

    samples = _load_samples(args.dataset_dir)
    for _ in range(args.warmup):
        for _, audio, ref, _ in samples:
            svc._evaluate_sync(audio, ref)
    timings.clear()

    print(
        f"cpus={args.cpus or 'all'} torch_threads={torch.get_num_threads()} "
        f"concurrency={args.concurrency} runs={args.runs} "
        f"model_load={load_s:.1f}s rss_after_load={rss_loaded:.0f}MB"
    )
    header = "| sample | " + " | ".join(f"{s} p50" for s in STAGES) + " | total p50 | total p90 |"
    print(header)
    print("|" + "---|" * (len(STAGES) + 3))

    if args.concurrency == 1:
        for name, audio, ref, dur in samples:
            first = len(timings)
            for _ in range(args.runs):
                svc._evaluate_sync(audio, ref)
            print(_row(f"{name} ({dur:.1f}s)", timings[first:]))
    else:
        jobs = [(audio, ref) for _, audio, ref, _ in samples] * args.runs
        t = time.perf_counter()
        with ThreadPoolExecutor(args.concurrency) as ex:
            list(ex.map(lambda job: svc._evaluate_sync(*job), jobs))
        wall = time.perf_counter() - t
        print(_row("all samples, concurrent", timings))
        print(f"\nthroughput: {len(jobs) / wall:.2f} req/s ({len(jobs)} requests, {wall:.1f}s)")

    print(f"rss_after_runs={proc.memory_info().rss / 2**20:.0f}MB (ms values)")


if __name__ == "__main__":
    main()
