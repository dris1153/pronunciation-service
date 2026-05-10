"""INT8 vs FP32 latency spike (Phase 03 / Finding 5).

Decision rule:
- INT8 speedup >= 1.4×  → proceed with full Phase 03 default-flip PR
- 1.2× <= speedup < 1.4× → proceed but adjust target downward
- speedup < 1.2×        → ABORT Phase 03; ship only g2p cache bump

Run:
    python debugs/spike_int8_benchmark.py [--samples PATH ...]

If no --samples are given, generates 5 synthetic 3-second sine sweeps.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import torch
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

ITER = 10
WARMUP = 2


def _synth_audio(seconds: float = 3.0, sr: int = 16000) -> np.ndarray:
    t = np.linspace(0, seconds, int(seconds * sr), dtype=np.float32)
    return (np.sin(2 * np.pi * 220 * t) * 0.5).astype(np.float32)


def _load_audio(path: Path, sr: int = 16000) -> np.ndarray:
    import soundfile as sf

    data, _sr = sf.read(str(path), dtype="float32")
    if data.ndim > 1:
        data = data.mean(axis=1)
    return data


def _bench(model, processor, samples: list[np.ndarray]) -> dict:
    timings: list[float] = []
    with torch.no_grad():
        for audio in samples:
            inputs = processor(audio, sampling_rate=16000, return_tensors="pt", padding=True)
            for _ in range(WARMUP):
                _ = model(inputs.input_values).logits
            for _ in range(ITER):
                start = time.perf_counter()
                _ = model(inputs.input_values).logits
                timings.append(time.perf_counter() - start)
    timings.sort()
    return {
        "p50_ms": statistics.median(timings) * 1000,
        "p90_ms": timings[int(0.9 * len(timings))] * 1000,
        "p99_ms": timings[int(0.99 * len(timings))] * 1000,
        "min_ms": timings[0] * 1000,
        "n": len(timings),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=Path, nargs="*", default=[])
    parser.add_argument("--model", default="facebook/wav2vec2-base-960h")
    parser.add_argument("--cache-dir", default="./model_cache")
    args = parser.parse_args()

    if args.samples:
        samples = [_load_audio(p) for p in args.samples]
    else:
        print("No --samples provided; using 5 synthetic 3s sine sweeps.")
        samples = [_synth_audio() for _ in range(5)]

    print(f"Loading {args.model} ...")
    processor = Wav2Vec2Processor.from_pretrained(args.model, cache_dir=args.cache_dir)
    base_model = Wav2Vec2ForCTC.from_pretrained(args.model, cache_dir=args.cache_dir)
    base_model.eval()

    print("Benchmarking FP32 ...")
    fp32 = _bench(base_model, processor, samples)
    print(f"  FP32 → p50={fp32['p50_ms']:.1f}ms p90={fp32['p90_ms']:.1f}ms n={fp32['n']}")

    print("Quantizing to INT8 ...")
    from torch.quantization import quantize_dynamic

    int8_model = quantize_dynamic(base_model, {torch.nn.Linear}, dtype=torch.qint8)
    int8_model.eval()

    print("Benchmarking INT8 ...")
    int8 = _bench(int8_model, processor, samples)
    print(f"  INT8 → p50={int8['p50_ms']:.1f}ms p90={int8['p90_ms']:.1f}ms n={int8['n']}")

    speedup = fp32["p50_ms"] / int8["p50_ms"]
    print(f"\nSpeedup p50: {speedup:.2f}×")
    if speedup >= 1.4:
        print("DECISION: PROCEED — INT8 default flip is justified.")
        return 0
    if speedup >= 1.2:
        print("DECISION: MARGINAL — proceed but adjust latency targets downward.")
        return 0
    print("DECISION: ABORT — INT8 not worth the eval risk; ship only g2p cache bump.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
