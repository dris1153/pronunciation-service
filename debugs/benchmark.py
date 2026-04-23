"""Benchmark: measure resource usage per request for wav2vec2-base-960h."""
from __future__ import annotations

import gc
import os
import time

import numpy as np
import psutil
import torch

# ── Measure baseline memory ──────────────────────────────────
process = psutil.Process(os.getpid())
mem_before_import = process.memory_info().rss / (1024 * 1024)
print(f"[1] Baseline RAM (after imports): {mem_before_import:.1f} MB")

# ── Load model ───────────────────────────────────────────────
print("\n[2] Loading model...")
t0 = time.perf_counter()

from app.services.asr_service import get_asr_service  # noqa: E402
from app.services.ipa_service import get_ipa_service  # noqa: E402
from app.services.gop_service import get_gop_service  # noqa: E402

asr = get_asr_service()
ipa = get_ipa_service()
gop = get_gop_service()

load_time = time.perf_counter() - t0
mem_after_model = process.memory_info().rss / (1024 * 1024)
model_ram = mem_after_model - mem_before_import
print(f"   Model load time: {load_time:.2f}s")
print(f"   RAM after model load: {mem_after_model:.1f} MB (+{model_ram:.1f} MB for model)")

# ── Generate synthetic audio (3 seconds, 16kHz) ─────────────
SR = 16000
DURATIONS = [3, 5, 10]  # seconds
REFERENCE_TEXT = "hello world"
N_WARMUP = 2
N_RUNS = 5

print(f"\n[3] Benchmarking inference (warmup={N_WARMUP}, runs={N_RUNS})")
print("=" * 65)

for dur in DURATIONS:
    # Create a realistic-ish synthetic waveform (white noise + sine)
    t = np.linspace(0, dur, SR * dur, dtype=np.float32)
    waveform = 0.3 * np.sin(2 * np.pi * 440 * t) + 0.05 * np.random.randn(len(t)).astype(np.float32)

    # Warmup
    for _ in range(N_WARMUP):
        _ = asr.transcribe(waveform, SR)
        gc.collect()

    # Benchmark: ASR transcription
    mem_before_infer = process.memory_info().rss / (1024 * 1024)
    latencies = []
    peak_mem = 0.0

    for i in range(N_RUNS):
        gc.collect()
        start = time.perf_counter()

        transcription = asr.transcribe(waveform, SR)
        log_probs = asr.get_ctc_log_probs(waveform, SR)
        ref_ipa = ipa.text_to_ipa(REFERENCE_TEXT)
        gop_result = gop.score(log_probs, REFERENCE_TEXT)

        elapsed = time.perf_counter() - start
        latencies.append(elapsed)

        current_mem = process.memory_info().rss / (1024 * 1024)
        peak_mem = max(peak_mem, current_mem)

    mem_during_infer = peak_mem - mem_before_infer
    avg_lat = sum(latencies) / len(latencies)
    min_lat = min(latencies)
    max_lat = max(latencies)

    print(f"\n  Audio duration: {dur}s")
    print(f"  Latency  — avg: {avg_lat:.3f}s | min: {min_lat:.3f}s | max: {max_lat:.3f}s")
    print(f"  Peak RAM during inference: {peak_mem:.1f} MB (+{mem_during_infer:.1f} MB over baseline)")
    print(f"  Transcription sample: '{transcription[:60]}'")

# ── CPU usage estimate ───────────────────────────────────────
print("\n[4] System info")
print(f"   CPU cores (logical): {psutil.cpu_count(logical=True)}")
print(f"   CPU cores (physical): {psutil.cpu_count(logical=False)}")
print(f"   Total system RAM: {psutil.virtual_memory().total / (1024**3):.1f} GB")
print(f"   Current process RAM: {process.memory_info().rss / (1024**2):.1f} MB")

# ── Cost estimation ──────────────────────────────────────────
print("\n[5] Cost estimation (Railway / cloud VPS)")
avg_3s = latencies[0] if len(DURATIONS) == 1 else sum(latencies[:N_RUNS]) / N_RUNS

total_ram_gb = mem_after_model / 1024
print(f"   Required RAM per worker: ~{mem_after_model:.0f} MB ({total_ram_gb:.2f} GB)")
print(f"   Avg latency (last duration): {avg_lat:.3f}s")
print(f"   Max concurrent requests (1 worker): ~{1/avg_lat:.1f} req/s")

# Railway pricing: ~$10/GB RAM/month + $0.000463/vCPU-min
railway_ram_cost = total_ram_gb * 10  # $/month for RAM
print(f"\n   Railway Starter (estimated):")
print(f"     RAM cost: ~${railway_ram_cost:.2f}/month")
print(f"     vCPU cost: ~$0.000463/vCPU-minute")

# Per-request cost: CPU time * vCPU rate
cpu_cost_per_req = avg_lat / 60 * 0.000463
ram_per_req_month = railway_ram_cost  # Fixed cost, amortise over requests
print(f"\n   Per-request cost breakdown:")
print(f"     CPU cost per request: ${cpu_cost_per_req:.8f}")
print(f"     If 1000 requests/day:")
reqs_per_month = 1000 * 30
total_monthly = railway_ram_cost + (cpu_cost_per_req * reqs_per_month) + 5  # +$5 base
print(f"       Monthly total: ~${total_monthly:.2f} (RAM + CPU + base)")
print(f"       Per request: ~${total_monthly / reqs_per_month:.6f}")

print(f"\n     If 100 requests/day:")
reqs_per_month_100 = 100 * 30
total_monthly_100 = railway_ram_cost + (cpu_cost_per_req * reqs_per_month_100) + 5
print(f"       Monthly total: ~${total_monthly_100:.2f}")
print(f"       Per request: ~${total_monthly_100 / reqs_per_month_100:.6f}")

print("\nDone!")
