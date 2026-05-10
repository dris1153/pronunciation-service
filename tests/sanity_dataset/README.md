# Sanity Dataset

5 synthetic recordings used by `tests/test_scoring_sanity.py` and
`scripts/sanity_eval.py` to detect scoring regressions across deploys.

## Why synthetic?

All audio is gTTS-generated → 0 PII, 0 consent issues, 0 redistribution
licensing concerns. Also makes the dataset deterministic given the gTTS
endpoint output.

## Layout

```
sanity_dataset/
├── good_001_phrase/
│   ├── audio.wav         # 16 kHz mono, ≤ 10 sec
│   ├── reference.txt     # text the user "should have said"
│   └── expected.json     # {min_score, max_score, tier, synthesised_text}
├── good_002_sentence/
├── good_003_paragraph/
├── poor_001_substitution/
└── poor_002_omission/
```

## Regenerating

```
pip install gtts
python scripts/generate_sanity_audio.py
```

After regeneration, refresh the baseline:

```
python scripts/sanity_eval.py \
    --api-url=http://localhost:8000 \
    --api-key=$API_KEY \
    --save-baseline=tests/sanity_dataset/sanity_baseline.json
```

## Adding a recording

1. Append a tuple to `RECORDINGS` in `scripts/generate_sanity_audio.py`.
2. Re-run the generation script.
3. Regenerate the baseline (above).
4. Commit `audio.wav`, `reference.txt`, `expected.json`, and the new
   baseline JSON together.

## Caveats

- gTTS quality drifts when Google updates voices. If the dataset starts
  failing globally, regenerate.
- Synthetic English ≠ accented user speech. Production logs (Phase 05)
  surface real-world score distributions; expand this dataset only when
  drift is observed there.
