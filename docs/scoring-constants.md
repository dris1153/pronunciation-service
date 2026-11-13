<!-- doc-id: docs-scoring-constants | rev: 6006c067 -->
# Scoring Constants Rationale

Why each hardcoded scoring constant has the value it does. Bumping any of
them requires running the sanity suite:

```
python scripts/sanity_eval.py \
    --api-key=$API_KEY \
    --compare-baseline=tests/sanity_dataset/sanity_baseline.json
```

If the comparator reports a deviation > 5pt or any tier flip, decide:

- **Intentional recalibration?** → update `sanity_baseline.json` and document
  the change here.
- **Regression?** → revert.

---

## 1. GOP calibration: `_FLOOR = -25.0`, `_CEIL = -3.0`

- **Where:** `app/services/gop_service.py` (normalisation step)
- **Empirical:** CTC log-probs for correctly pronounced phonemes range from
  about -25 (very poor) to -3 (excellent). Even perfect TTS rarely exceeds
  -3 because softmax mass is distributed across the full vocabulary.
- **Risk if changed:** Linear remap → all GOP scores shift proportionally,
  which feeds into accuracy_score (45% weight) and overall_score.

## 2. Phoneme similarity partial credit: `0.3`

- **Where:** `app/services/pronunciation_service.py` — phoneme alignment
  cost matrix.
- **Empirical:** Substituting a phoneme with one in the same phonetic group
  (e.g. ɛ↔æ, both front vowels) gets 0.3 vs 1.0 (match) or 0.0 (different
  group). Higher value would inflate accuracy versus Azure's stricter
  scoring; lower value penalises minor accent variation too harshly.
- **Risk if changed:** Per-phoneme accuracy shifts → aggregate IPA accuracy
  moves linearly → accuracy_score (55% weight) shifts.

## 3. Mispronunciation threshold: `60.0`

- **Where:** `app/services/pronunciation_service.py` —
  `_MISPRONUNCIATION_THRESHOLD`.
- **Rationale:** Aligned with Azure Speech SDK convention — words below 60%
  IPA accuracy are flagged as mispronunciations.
- **Risk if changed:** Word-level `error_type` classification shifts; words
  newly classified as mispronounced no longer count toward
  `completeness_score`.

## 4. Wav2Vec2 hop size: `320`

- **Where:** `app/services/pronunciation_service.py` — `_HOP_SIZE`.
- **Rationale:** Wav2Vec2 architecture: 20 ms frames at 16 kHz = 320 samples
  per frame. Used for word-timing forced alignment that feeds
  `fluency_score`.
- **Risk if changed:** Any model swap that changes the hop also REQUIRES
  updating this constant; otherwise word timings become wrong → fluency
  metric returns garbage.
- **CI guard:** Sanity suite catches drift if model is upgraded without
  updating the hop.

## 5. Speed penalty inconsistency: `30 pts/wps` (prosody) vs `20 pts/wps` (fluency)

- **Where:** `app/services/prosody_service.py` (~line 178) and
  `app/services/pronunciation_service.py` — `_RATE_PENALTY_PER_WPS`.
- **Status:** **Known inconsistency.** The historical reason for the
  asymmetric penalty is not documented in the codebase. Flagged for v2
  calibration once production data is available.
- **Risk if unified:** Both sub-scores shift → overall_score weights change
  → sanity baseline must be regenerated.

---

## v2 constants (`app/services/v2/`)

Sections 1-5 are v1 constants. The v2 pipeline has its own, mostly learned from data:

| Constant | Value | Where | Why |
| --- | --- | --- | --- |
| `SCORE_CURVE_EXPONENT` | `1.4` | `pronunciation_v2_service.py` | Maps the expert-scale predictions (mostly 6-10) onto the stricter v1 scale: `100 x (s/10)^1.4`. 1.3 left `poor_001` at 59.4, too close to the 60 line. Tuned on 5 synthetic clips; recalibrate on real learner audio. Moves utterance correlations by <= 0.005 |
| `MIN_HEARD_RATIO` | `0.2` | `pronunciation_v2_service.py` | Below 20% of expected phones heard, the audio is treated as no speech (zero score). Lowest share in real speechocean762 speech is 0.31 |
| `mdd_threshold` | `1.48` (of 2) | `scorer.json` | Phone score below this means `is_correct_ipa = false`. Chosen to maximise mispronunciation F1 on out-of-fold train predictions |
| `MIN_SAMPLES` | `400` | `phone_model.py` | The HuBERT conv front-end rejects shorter audio (25 ms) |
| `Z_CLIP` | `10` | `scorer.py` | Rare-phone one-hots have tiny variance; unclipped z-scores reached ~200 and broke the fit |
| Mispronunciation word threshold | `60` | `scoring_rules.py` | Shared with v1 (Azure uses the same) |
| Break thresholds | `0.8 s` / `0.15 s` | `scoring_rules.py` | Shared with v1; v2 applies them to the aligned word spans |

Changing the phone model, the feature layout or the phone inventory requires retraining `scorer.json` ([training.md](training.md)). Quality is checked with `scripts/speechocean762_eval.py --api v2` ([evaluation.md](evaluation.md)).

## How to update a constant safely

1. Make the change in the relevant service file.
2. Restart the local server.
3. Run:
   ```
   python scripts/sanity_eval.py \
       --api-key=$API_KEY \
       --compare-baseline=tests/sanity_dataset/sanity_baseline.json
   ```
4. If exit code 0: change is within tolerance. Commit alongside an entry in
   the changelog below.
5. If exit code 1 with intentional recalibration: regenerate baseline, commit
   both files, document the recalibration here.
6. If exit code 1 with unintended regression: revert.

## Changelog

- _2026-05-04_ — Initial documentation (Phase 06).
