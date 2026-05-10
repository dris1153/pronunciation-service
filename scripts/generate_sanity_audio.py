"""Generate the 5-recording sanity dataset for the regression suite.

Phase 06 / Finding 6 — synthetic, no PII, deterministic given gTTS network.

Run:
    python scripts/generate_sanity_audio.py

Outputs to tests/sanity_dataset/<rec_id>/{audio.wav, reference.txt, expected.json}.
Requires: ``gtts`` package (in requirements.txt) and ffmpeg on PATH.

Re-run any time gTTS output drifts; regenerate baseline after with
``scripts/sanity_eval.py --save-baseline=...``.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from gtts import gTTS
except ImportError:
    print("ERROR: gtts not installed. Run: pip install gtts==2.5.4", file=sys.stderr)
    sys.exit(1)

DATASET = Path(__file__).resolve().parent.parent / "tests" / "sanity_dataset"

# (recording_id, reference_text, synthesised_text, tier, (min, max) score band)
RECORDINGS: list[tuple[str, str, str, str, tuple[int, int]]] = [
    (
        "good_001_phrase",
        "hello world",
        "hello world",
        "good",
        (70, 100),
    ),
    (
        "good_002_sentence",
        "the quick brown fox jumps over the lazy dog",
        "the quick brown fox jumps over the lazy dog",
        "good",
        (70, 100),
    ),
    (
        "good_003_paragraph",
        "today is a beautiful day let us go for a walk in the park",
        "today is a beautiful day let us go for a walk in the park",
        "good",
        (70, 100),
    ),
    # "Poor" recordings: ref says A, audio says B → mispronunciation by design.
    (
        "poor_001_substitution",
        "hello world",
        "yellow word",
        "poor",
        (20, 60),
    ),
    (
        "poor_002_omission",
        "the quick brown fox",
        "the fox",
        "poor",
        (20, 60),
    ),
]


def _synthesise(text: str, mp3_path: Path) -> None:
    tts = gTTS(text=text, lang="en", slow=False)
    tts.save(str(mp3_path))


def _convert_to_wav(mp3: Path, wav: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not on PATH — cannot convert MP3 → WAV.")
    subprocess.run(
        [ffmpeg, "-y", "-loglevel", "error",
         "-i", str(mp3), "-ar", "16000", "-ac", "1", str(wav)],
        check=True,
    )


def main() -> None:
    DATASET.mkdir(parents=True, exist_ok=True)
    for rec_id, ref_text, synth_text, tier, (lo, hi) in RECORDINGS:
        rec_dir = DATASET / rec_id
        rec_dir.mkdir(parents=True, exist_ok=True)

        mp3 = rec_dir / "_temp.mp3"
        wav = rec_dir / "audio.wav"
        print(f"  → {rec_id}: synth={synth_text!r}")
        _synthesise(synth_text, mp3)
        _convert_to_wav(mp3, wav)
        mp3.unlink()

        (rec_dir / "reference.txt").write_text(ref_text, encoding="utf-8")
        (rec_dir / "expected.json").write_text(
            json.dumps(
                {"min_score": lo, "max_score": hi, "tier": tier,
                 "synthesised_text": synth_text},
                indent=2,
            ),
            encoding="utf-8",
        )
    print(f"Done. {len(RECORDINGS)} recordings written under {DATASET}")


if __name__ == "__main__":
    main()
