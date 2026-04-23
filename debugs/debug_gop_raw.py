"""Debug script: measure raw GOP scores to find empirical range.

Uses Google TTS to generate "perfect" audio, then inspects raw
log-prob values BEFORE normalisation to find the true range.
"""
from __future__ import annotations

import io
import statistics
import sys

import numpy as np
import torch

# ── Setup ────────────────────────────────────────────────────────────────────

print("Loading services (this may take a moment)...")
from app.services.asr_service import get_asr_service
from app.services.gop_service import GOPService, get_gop_service, _IPA_TO_WAV2VEC
from app.services.ipa_service import get_ipa_service
from app.utils.audio import load_audio_from_bytes
from app.utils.text import text_to_words

asr = get_asr_service()
ipa = get_ipa_service()
gop = get_gop_service()

# ── Generate TTS audio ──────────────────────────────────────────────────────

TEST_SENTENCES = [
    "hello world",
    "the cat sat on the mat",
    "good morning everyone",
    "she sells sea shells by the sea shore",
    "how are you doing today",
]

try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False
    print("WARNING: gTTS not installed. Using synthetic audio (less realistic).")
    print("         Install with: pip install gtts")


def generate_tts_audio(text: str) -> tuple[np.ndarray, int]:
    """Generate audio bytes from Google TTS and load as waveform."""
    if HAS_GTTS:
        tts = gTTS(text=text, lang="en", slow=False)
        buf = io.BytesIO()
        tts.write_to_fp(buf)
        buf.seek(0)
        waveform, sr = load_audio_from_bytes(buf.read())
        return waveform, sr
    else:
        # Fallback: generate a 2-second sine wave (will give bad scores, but
        # shows the pipeline working)
        sr = 16000
        t = np.linspace(0, 2.0, sr * 2, dtype=np.float32)
        waveform = 0.3 * np.sin(2 * np.pi * 440 * t)
        return waveform, sr


# ── Collect raw GOP scores ──────────────────────────────────────────────────

print("\n" + "=" * 70)
print("RAW GOP SCORE ANALYSIS (before normalisation)")
print("=" * 70)

all_raw_scores: list[float] = []
vocab = asr.get_vocab()

for sentence in TEST_SENTENCES:
    print(f"\n{'─' * 60}")
    print(f"Sentence: \"{sentence}\"")

    waveform, sr = generate_tts_audio(sentence)
    print(f"  Audio: {len(waveform)/sr:.2f}s, {sr} Hz")

    # Transcribe first
    transcription = asr.transcribe(waveform, sr)
    print(f"  Transcription: \"{transcription}\"")

    # Get CTC log-probs
    log_probs = asr.get_ctc_log_probs(waveform, sr)
    n_frames = log_probs.size(0)
    print(f"  Frames: {n_frames}")

    # Build phoneme list (same as GOPService.score does)
    words = text_to_words(sentence)
    total_phonemes: list[tuple[int, str, str]] = []
    for wi, w in enumerate(words):
        phonemes = ipa.word_to_phoneme_list(w)
        for p in phonemes:
            total_phonemes.append((wi, w, p))

    n_phonemes = len(total_phonemes)
    base_frames = n_frames // n_phonemes
    remainder = n_frames % n_phonemes
    extra_start = n_phonemes - remainder

    print(f"  Phonemes: {n_phonemes}, base_frames: {base_frames}, remainder: {remainder}")
    print(f"  Per-phoneme raw scores:")

    frame_idx = 0
    sentence_raw_scores: list[float] = []

    for phoneme_pos, (word_idx, word_str, ipa_phoneme) in enumerate(total_phonemes):
        frames = base_frames + (1 if phoneme_pos >= extra_start else 0)
        start = frame_idx
        end = min(frame_idx + frames, n_frames)
        frame_idx = end

        # Compute raw score (same logic as GOPService._compute_phoneme_gop)
        if start >= end:
            raw = -30.0
        else:
            token = _IPA_TO_WAV2VEC.get(ipa_phoneme, ipa_phoneme.upper())
            token_idx = vocab.get(token)

            if token_idx is None:
                segment = log_probs[start:end]
                raw = float(segment.max(dim=-1).values.mean().item())
                mapped_to = f"FALLBACK (no '{token}' in vocab)"
            else:
                segment_lp = log_probs[start:end, token_idx]
                raw = float(segment_lp.mean().item())
                mapped_to = f"'{token}' (idx={token_idx})"

        # Also compute normalised for comparison
        clamped = max(raw, -30.0)
        normalised = ((clamped + 30.0) / 30.0) * 100.0
        normalised = round(min(max(normalised, 0.0), 100.0), 2)

        sentence_raw_scores.append(raw)
        all_raw_scores.append(raw)

        print(f"    [{word_str:>10}] {ipa_phoneme:>3} → {mapped_to:>20}  "
              f"raw={raw:>8.3f}  norm={normalised:>6.1f}")

    avg_raw = statistics.mean(sentence_raw_scores)
    avg_norm = ((max(avg_raw, -30) + 30) / 30) * 100
    print(f"  ── Sentence avg raw: {avg_raw:.3f}, avg normalised: {avg_norm:.1f}")

# ── Summary statistics ──────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("SUMMARY — All raw GOP scores across all sentences")
print("=" * 70)
print(f"  Count:      {len(all_raw_scores)}")
print(f"  Min:        {min(all_raw_scores):.3f}")
print(f"  Max:        {max(all_raw_scores):.3f}")
print(f"  Mean:       {statistics.mean(all_raw_scores):.3f}")
print(f"  Median:     {statistics.median(all_raw_scores):.3f}")
print(f"  Stdev:      {statistics.stdev(all_raw_scores):.3f}")

sorted_scores = sorted(all_raw_scores)
n = len(sorted_scores)
p5 = sorted_scores[int(n * 0.05)]
p10 = sorted_scores[int(n * 0.10)]
p25 = sorted_scores[int(n * 0.25)]
p50 = sorted_scores[int(n * 0.50)]
p75 = sorted_scores[int(n * 0.75)]
p90 = sorted_scores[int(n * 0.90)]
p95 = sorted_scores[int(n * 0.95)]

print(f"\n  Percentiles:")
print(f"    P5:       {p5:.3f}")
print(f"    P10:      {p10:.3f}")
print(f"    P25:      {p25:.3f}")
print(f"    P50:      {p50:.3f}")
print(f"    P75:      {p75:.3f}")
print(f"    P90:      {p90:.3f}")
print(f"    P95:      {p95:.3f}")

print(f"\n  Current normalisation: [-30, 0] → [0, 100]")
print(f"    Mean normalised:  {((max(statistics.mean(all_raw_scores), -30) + 30) / 30) * 100:.1f}")
print(f"    Best normalised:  {((max(max(all_raw_scores), -30) + 30) / 30) * 100:.1f}")

print(f"\n  Suggested empirical range: [{p5:.1f}, {p95:.1f}]")
suggested_low = p5
suggested_high = max(all_raw_scores)
print(f"  If normalising [{suggested_low:.1f}, {suggested_high:.1f}] → [0, 100]:")
best_norm = ((max(all_raw_scores) - suggested_low) / (suggested_high - suggested_low)) * 100
mean_norm = ((statistics.mean(all_raw_scores) - suggested_low) / (suggested_high - suggested_low)) * 100
print(f"    Mean → {mean_norm:.1f}")
print(f"    Best → {best_norm:.1f}")
