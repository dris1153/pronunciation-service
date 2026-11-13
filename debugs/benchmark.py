"""Per-stage latency benchmark for the /evaluate pipeline (in-process, real models).

Usage:
    python debugs/benchmark.py [--api v1|v2] [--int8] [--cpus 2] [--concurrency 1]
                               [--runs 5] [--dataset-dir tests/sanity_dataset]

Each sub-directory of --dataset-dir must hold ``audio.wav`` + ``reference.txt``
(generate the sanity set with ``scripts/generate_sanity_audio.py``).

--cpus pins the process to N cores, mimicking an N-vCPU VPS (Docker ``--cpus``
is not available on every dev box). --concurrency K runs K requests in parallel
threads, like K inference slots, and reports throughput. Torch threads default
to N // K like the app (app.core.concurrency.torch_threads_per_slot);
--threads T overrides that. --api v2 times the torch-free ONNX phone pipeline
(--int8 selects model.int8.onnx) and never imports torch, so its RSS is the v2-only footprint.
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
V1_STAGES = ("decode", "asr", "ipa", "gop", "prosody")
V2_STAGES = ("decode", "onnx", "align", "score")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--api", default="v1", choices=["v1", "v2"])
    p.add_argument("--int8", action="store_true", help="v2: use the INT8 model")
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


def _row(label: str, timings: list[dict], stages: tuple[str, ...]) -> str:
    cells = [f"{statistics.median(t[s] for t in timings):.0f}" for s in stages]
    totals = [t["total"] for t in timings]
    return (
        f"| {label} | " + " | ".join(cells)
        + f" | {statistics.median(totals):.0f} | {_p(totals, 0.9):.0f} |"
    )


def _make_v2_runner(args: argparse.Namespace, threads: int, timings: list[dict]):
    from app.core.config import get_settings
    from app.services.ipa_service import get_ipa_service
    from app.services.v2.gop_features import analyse_posteriors
    from app.services.v2.phone_model import PhoneModel
    from app.services.v2.scorer import Scorer
    from app.utils.audio import load_audio_from_bytes
    from app.utils.text import text_to_words

    model_dir = Path(get_settings().phone_model_dir)
    model = PhoneModel(model_dir, args.int8, threads)
    scorer = Scorer.load(model_dir / "scorer.json")
    ipa = get_ipa_service()

    def run(audio: bytes, ref: str) -> None:
        t = [time.perf_counter()]
        wave, _ = load_audio_from_bytes(audio)
        t.append(time.perf_counter())
        log_probs = model.log_posteriors(wave)
        t.append(time.perf_counter())
        words = [(w, ipa.word_to_phoneme_list(w)) for w in text_to_words(ref)]
        analysis = analyse_posteriors(log_probs, words, model.vocab)
        t.append(time.perf_counter())
        scorer.score(analysis)
        t.append(time.perf_counter())
        ms = [(b - a) * 1000 for a, b in zip(t, t[1:])]
        timings.append(dict(zip(V2_STAGES, ms)) | {"total": sum(ms)})

    return V2_STAGES, run


def main() -> None:
    args = _parse_args()
    import psutil

    proc = psutil.Process()
    if args.cpus:
        proc.cpu_affinity(list(range(args.cpus)))

    threads = args.threads or (max(1, args.cpus // args.concurrency) if args.cpus else 0)
    from loguru import logger

    timings: list[dict] = []
    logger.remove()
    t0 = time.perf_counter()
    if args.api == "v2":
        stages, run = _make_v2_runner(args, threads, timings)
        thread_info = f"ort_threads={threads or 'auto'} int8={args.int8}"
    else:
        import torch

        if threads:
            torch.set_num_threads(threads)
        logger.add(
            lambda m: timings.append(m.record["extra"]["stage_ms"]),
            filter=lambda r: r["message"] == "evaluate_timing",
        )
        from app.services.pronunciation_service import get_pronunciation_service

        svc = get_pronunciation_service()
        stages, run = V1_STAGES, svc._evaluate_sync
        thread_info = f"torch_threads={torch.get_num_threads()}"
    load_s = time.perf_counter() - t0
    rss_loaded = proc.memory_info().rss / 2**20

    samples = _load_samples(args.dataset_dir)
    for _ in range(args.warmup):
        for _, audio, ref, _ in samples:
            run(audio, ref)
    timings.clear()

    print(
        f"api={args.api} cpus={args.cpus or 'all'} {thread_info} "
        f"concurrency={args.concurrency} runs={args.runs} "
        f"model_load={load_s:.1f}s rss_after_load={rss_loaded:.0f}MB"
    )
    header = "| sample | " + " | ".join(f"{s} p50" for s in stages) + " | total p50 | total p90 |"
    print(header)
    print("|" + "---|" * (len(stages) + 3))

    if args.concurrency == 1:
        for name, audio, ref, dur in samples:
            first = len(timings)
            for _ in range(args.runs):
                run(audio, ref)
            print(_row(f"{name} ({dur:.1f}s)", timings[first:], stages))
    else:
        jobs = [(audio, ref) for _, audio, ref, _ in samples] * args.runs
        t = time.perf_counter()
        with ThreadPoolExecutor(args.concurrency) as ex:
            list(ex.map(lambda job: run(*job), jobs))
        wall = time.perf_counter() - t
        print(_row("all samples, concurrent", timings, stages))
        print(f"\nthroughput: {len(jobs) / wall:.2f} req/s ({len(jobs)} requests, {wall:.1f}s)")

    print(f"rss_after_runs={proc.memory_info().rss / 2**20:.0f}MB (ms values)")


if __name__ == "__main__":
    main()
