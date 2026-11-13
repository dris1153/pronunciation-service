<!-- doc-id: docs-scoring-v1 | rev: f3f95227 -->
# Scoring v1 (Wav2Vec2 ASR pipeline)

How `POST /api/v1/evaluate` produces its scores: word ASR, g2p IPA references, CTC-posterior GOP, pitch prosody and Azure-style sub-scores.
This pipeline is unchanged. The newer phoneme-level pipeline is described in [scoring-v2.md](scoring-v2.md); constants and why they were chosen are in [scoring-constants.md](scoring-constants.md).

Measured weaknesses of v1 on speechocean762 (adults): phone-level GOP correlates at 0.03 with expert scores, prosody at 0.11, and heard-vs-expected mispronunciation detection has F1 0.27 (precision 0.16). Most large errors trace back to ASR gibberish on accented speech. See [evaluation.md](evaluation.md).

## Pipeline

### Pipeline Overview

```
Audio bytes → ASR (Wav2Vec2) → Transcription → IPA comparison + GOP scoring → Unified response
```

1. **Audio Processing** — Load and resample audio to 16 kHz mono float32 (librosa)
2. **ASR Transcription** — Wav2Vec2 transcribes what was actually said
3. **IPA Conversion** — Both reference and transcription → IPA phonemes (g2p_en + ARPAbet→IPA mapping)
4. **IPA Comparison** — Separate DP alignment for words (`_align_words`) and phonemes (`_align_phonemes`) with ε-tolerance back-trace
5. **GOP Scoring** — CTC log-posteriors with remainder-aware frame distribution (no dropped tail frames)
6. **Prosody Analysis** — Pitch extraction via librosa pyin, pitch variance/range/contour scoring, monotone detection
7. **Error Classification** — Each word receives an `ErrorType`: `None`, `Mispronunciation`, `Omission`, `Insertion`, `UnexpectedBreak`, or `MissingBreak`
8. **Sub-scores** — `accuracy_score` = 55% IPA + 45% GOP; `completeness_score` = accuracy-weighted ratio of correctly pronounced reference words; `fluency_score` = speech rate + pause analysis; `prosody_score` = intonation + speed + rhythm
9. **Combined Score** — Azure-style weighted formula: sort 4 sub-scores low→high, `0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3`

### Scoring Formula

#### Accuracy Score (sub-score)

Combines phoneme-level IPA comparison and GOP scoring:

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

#### Completeness Score (sub-score)

Measures how many reference words were **correctly** pronounced by the speaker:

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

A word is "correctly pronounced" if:

1. The alignment operation is `match` or `substitute` (word was attempted), **and**
2. The word-level IPA accuracy ≥ 60% (`_MISPRONUNCIATION_THRESHOLD`)

Omitted (`delete`) words and mispronounced words (accuracy < 60%) are not counted. Extra spoken words (`insert`) do not affect completeness.

#### Fluency Score (sub-score)

Measures speech fluidity using word-level CTC frame timing from GOP forced alignment:

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

**Speech rate** — deviation from the ideal rate (~3.0 words/sec). Rates within a ±0.5 wps tolerance band receive full marks; deviations beyond that are penalised at 20 points per wps.

**Pause penalty** — long gaps (>0.8s) between consecutive words reduce fluency, modelling hesitations and unexpected breaks. Each excess second of pause costs 15 points.

Azure defines fluency as "how closely the speech matches a native speaker's use of silent breaks between words" — pause patterns are the primary signal (60%), speech rate is a secondary proxy (40%).

#### Prosody Score (sub-score)

Evaluates pitch variation, speech rate, and rhythm naturalness. The prosody score has three components:

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

**Intonation score (55%)** — combines three pitch metrics:

```math
IntonationScore = 0.50 \times VarianceScore + 0.30 \times RangeScore + 0.20 \times ContourScore
```

- _Variance score_ — pitch coefficient of variation (CV = std/mean). CV ≤ `monotone_threshold` (0.08) = score 0; CV ≥ `cv_upper` (0.25) = score 100. Linear interpolation between.
- _Range score_ — pitch range in semitones. 0 st = score 0; ≥ 15 st = score 100. Linear interpolation.
- _Contour score_ — direction change ratio in pitch contour. Target ratio 0.45 gets full marks; deviations penalised linearly.

**Speed score (20%)** — words-per-second deviation from ideal 3.0 wps (±0.5 tolerance). Each 1 wps beyond tolerance → −30 points.

**Rhythm score (25%)** — normalised Pairwise Variability Index (nPVI). Measures stress-timing naturalness; native English nPVI ~50–70, syllable-timed ~30–40. Scored linearly: nPVI ≤30 → 0, nPVI ≥70 → 100.

**Monotone detection** — when pitch CV < threshold (0.08), `is_monotone = True` and prosody score is capped at 30.

**Voiced ratio guard** — if less than 10% of frames are voiced, returns score 0 (insufficient voiced signal).

**Default behaviour** — when word durations are unavailable (no CTC timing), speed and rhythm default to 50 (neutral).

#### Overall Combined Score

Sub-scores are sorted low→high and combined using the Azure PronScore formula:

```math
CombinedScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3
```

The lowest sub-score gets the most weight (40%), heavily penalising the weakest dimension.

#### Word-Level Error Classification

Each word in the result receives an `error_type` based on alignment and accuracy:

| Condition                                       | ErrorType          |
| ----------------------------------------------- | ------------------ |
| Word aligned (match/substitute), accuracy ≥ 60% | `None`             |
| Word aligned (match/substitute), accuracy < 60% | `Mispronunciation` |
| Word in reference but not spoken                | `Omission`         |
| Word spoken but not in reference                | `Insertion`        |
| Long pause (>0.8s) detected before word         | `UnexpectedBreak`  |
| Missing pause at punctuation boundary (<0.15s)  | `MissingBreak`     |

Threshold: `60.0` (aligned with Azure Speech SDK).

#### IPA Accuracy (weight: 55%)

Reference and transcribed text are compared at **two levels** using Levenshtein-based sequence alignment (dynamic programming with `float64` precision and ε = 10⁻⁶ back-trace tolerance):

**Level 1 — Word alignment (`_align_words`):**

Reference and transcribed word lists are aligned using plain Levenshtein DP (no phonetic similarity costs — word equality is binary). Produces match / substitute / insert / delete operations. Extra words spoken by the user (insertions) are penalised in the overall score.

**Level 2 — Phoneme alignment (`_align_phonemes`, per word pair):**

For each aligned word pair, reference and actual phoneme sequences are aligned using the same DP algorithm. The edit distance uses **phonetic similarity** — substituting a phoneme with one from the same phonetic group (e.g. `ɛ` ↔ `æ`, both front vowels) costs less than replacing with a phoneme from a different group.

```
Reference IPA:   [h, ɛ, l, oʊ]
Actual IPA:      [h, ɛ, ə, l, oʊ]
Alignment:
  h  = h    ✓  match
  ɛ  = ɛ    ✓  match
  -  ← ə    ✗  insert (extra phoneme in actual)
  l  = l    ✓  match
  oʊ = oʊ   ✓  match
→ 4/4 correct ref phonemes = 100% (insertion penalised in overall score)
```

**Phoneme confidence scoring:**

| Alignment result                        | Confidence |
| --------------------------------------- | ---------- |
| Exact match                             | `1.0`      |
| Substitution (same phonetic group)      | `0.3`      |
| Substitution (different phonetic group) | `0.0`      |
| Deletion (missing in actual)            | `0.0`      |
| Insertion (extra in actual)             | `0.0`      |

**Per-word accuracy:**

```math
WordAccuracy = \frac{CorrectPhonemes}{RefPhonemesInWord} \times 100
```

**Overall IPA accuracy (with insertion penalty):**

```math
OverallIPA = \frac{\sum CorrectPhonemes}{\sum RefPhonemes + \sum InsertedPhonemes} \times 100
```

> Extra words spoken add their phoneme count to the denominator, reducing the overall accuracy.

#### GOP Score (weight: 45%)

GOP (Goodness of Pronunciation) uses CTC log-posteriors from Wav2Vec2:

**Step 1 — CTC log-posteriors:**

Audio → Wav2Vec2 → output logits → `log_softmax` → matrix `(T, V)` where T = frames, V = vocab size

**Step 2 — Remainder-aware frame segmentation:**

Divide T frames across N phonemes. Each phoneme gets a base allocation, with remainder frames distributed to the **last** phonemes:

```math
base = \lfloor T / N \rfloor,\quad remainder = T \bmod N
```

Phonemes at positions `[N - remainder, N)` get `base + 1` frames; earlier phonemes get `base` frames. This ensures **all T frames are used** — no tail frames are dropped.

**Step 3 — Raw GOP per phoneme:**

For each phoneme `p`, map to Wav2Vec2 vocab token via `_IPA_TO_WAV2VEC`, then compute mean log-probability over its assigned frames `[start, end)`:

```math
GOP_{raw}(p) = \frac{1}{d} \sum_{t=start}^{end-1} \log P(p \mid o_t)
```

where `d = end - start` is the number of frames assigned to phoneme `p`.

> If phoneme is not in vocab → fallback: use max log-prob across entire vocab for those frames.

**Step 4 — Normalise to [0, 100]:**

Empirically calibrated: CTC log-probs for correctly pronounced phonemes typically range from −25 (very poor) to −3 (excellent). Even "perfect" TTS audio rarely produces raw scores above −3 because CTC softmax always distributes probability mass across the full vocabulary.

```math
GOP_{norm} = \frac{\text{clamp}(GOP_{raw},\ -25,\ -3) - (-25)}{22} \times 100
```

Clamped to `[0, 100]`.

**Step 5 — Aggregate:**

- **Per-word GOP** = mean of phoneme GOP scores in that word
- **Overall GOP** = mean of all phoneme GOP scores

> Word boundaries use index-based tracking (not string equality), so duplicate words like "the cat and the dog" are handled correctly.

#### Combined Score

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

```math
OverallScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3 \quad (S_0 \leq S_1 \leq S_2 \leq S_3)
```

#### Quality Levels

| Score Range  | Level        | Feedback                             |
| ------------ | ------------ | ------------------------------------ |
| **80 – 100** | 🟢 Excellent | Speech closely matches the reference |
| **60 – 79**  | 🔵 Good      | Minor improvements could be made     |
| **40 – 59**  | 🟡 Fair      | Several sounds need practice         |
| **0 – 39**   | 🔴 Poor      | Significant improvement needed       |

### Scoring Example

```
Reference:     "the cat and the dog"
Transcription: "the cat an the dock"

Word alignment (DP):
  the  = the   ✓ match     → ErrorType: None
  cat  = cat   ✓ match     → ErrorType: None
  and  ≈ an    ~ substitute → ErrorType: depends on accuracy
  the  = the   ✓ match     → ErrorType: None
  dog  ≈ dock  ~ substitute → ErrorType: depends on accuracy

Phoneme alignment for "and" → "an":
  Reference: [æ, n, d]    Actual: [æ, n]
  æ = æ  ✓ match     confidence=1.0
  n = n  ✓ match     confidence=1.0
  d → ∅  ✗ delete    confidence=0.0
  → Word accuracy = 2/3 × 100 = 66.7%  → ErrorType: None (≥60%)

Phoneme alignment for "dog" → "dock":
  Reference: [d, ɑ, ɡ]    Actual: [d, ɑ, k]
  d = d  ✓ match     confidence=1.0
  ɑ = ɑ  ✓ match     confidence=1.0
  ɡ ≈ k  ✗ substitute (same group: voiced/voiceless plosive) confidence=0.3
  → Word accuracy = 2/3 × 100 = 66.7%  → ErrorType: None (≥60%)

Overall IPA = (3+3+2+3+2) / (3+3+3+3+3) = 13/15 × 100 = 86.7%

GOP Scoring: (per-phoneme CTC log-prob scores, normalised 0-100)
  → Overall GOP = 72.5 (example)

Sub-scores:
  Accuracy    = 86.7 × 0.55 + 72.5 × 0.45 = 47.7 + 32.6 = 80.3
  Completeness = 5/5 × 100 = 100.0  (all reference words attempted)
  Fluency      = 95.0  (normal speech rate, no long pauses)
  Prosody      = 78.0  (good pitch variation, not monotone)

Overall = sorted([80.3, 100.0, 95.0, 78.0]) = [78.0, 80.3, 95.0, 100.0]
        = 0.4 × 78.0 + 0.2 × 80.3 + 0.2 × 95.0 + 0.2 × 100.0
        = 31.2 + 16.06 + 19.0 + 20.0 = 86.3
Level = EXCELLENT ✔
```

