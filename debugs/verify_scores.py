"""Quick verification: compare old vs new normalisation + weights.

Uses Google TTS for "perfect" audio to confirm the score ceiling improved.
"""
from __future__ import annotations

import io

import numpy as np

print("Loading services …")
from app.services.pronunciation_service import get_pronunciation_service

svc = get_pronunciation_service()

try:
    from gtts import gTTS
except ImportError:
    print("ERROR: pip install gtts")
    raise SystemExit(1)


def tts_bytes(text: str) -> bytes:
    tts = gTTS(text=text, lang="en", slow=False)
    buf = io.BytesIO()
    tts.write_to_fp(buf)
    return buf.getvalue()


SENTENCES = [
    "hello world",
    "the cat sat on the mat",
    "good morning everyone",
    "she sells sea shells by the sea shore",
    "how are you doing today",
]

print("\n" + "=" * 70)
print("SCORE VERIFICATION  (new: [-25,-5] normalisation, 55/45 weights)")
print("=" * 70)

for sentence in SENTENCES:
    audio = tts_bytes(sentence)
    result = svc._evaluate_sync(audio, sentence)

    ipa_score = result.ipa_result.overall_ipa_accuracy
    gop_score = result.gop_result.overall_gop_score
    combined = result.overall_score
    level = result.level

    print(f"\n\"{sentence}\"")
    print(f"  IPA accuracy:  {ipa_score:6.2f}")
    print(f"  GOP score:     {gop_score:6.2f}")
    print(f"  Combined:      {combined:6.2f}  ({level})")
    print(f"  (check: 0.55×{ipa_score} + 0.45×{gop_score} = "
          f"{round(ipa_score * 0.55 + gop_score * 0.45, 2)})")

print("\n" + "=" * 70)
print("DONE")
