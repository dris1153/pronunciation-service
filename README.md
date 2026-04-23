# 🗣️ Pronunciation Validation Service

REST API service that evaluates English pronunciation quality by comparing audio recordings against reference text. Provides **IPA phoneme comparison**, **Goodness-of-Pronunciation (GOP) scoring**, **word-level error classification**, **fluency analysis**, **prosody & monotone detection**, and **Azure-compatible sub-scores** (accuracy, completeness, fluency, prosody).

## 🏗️ Architecture

```
pronuncation-validate/
├── app/
│   ├── api/                        # API layer (FastAPI)
│   │   ├── routes/
│   │   │   ├── health.py           # GET /health — public, no auth
│   │   │   ├── pronunciation.py    # POST /api/v1/evaluate — protected
│   │   │   ├── ipa.py              # GET /api/v1/text-analysis — protected
│   │   │   ├── transcribe.py       # POST /api/v1/transcribe — protected
│   │   │   └── model_info.py       # GET /api/v1/model-info — public
│   │   ├── dependencies.py         # DI: verify_api_key (one-time warning), get_pronunciation_svc
│   │   └── middleware.py           # CORS (configurable via env), global exception handlers
│   ├── core/                       # Configuration
│   │   ├── config.py               # pydantic-settings (from .env via absolute path, CORS property)
│   │   ├── concurrency.py          # asyncio.Semaphore — limits concurrent ML inference
│   │   ├── constants.py            # Shared constants (MIME types, upload limits — single source of truth)
│   │   └── logging.py              # Loguru setup
│   ├── models/                     # Domain models
│   │   └── schemas.py              # Pydantic v2 request/response schemas (ErrorType, WordResult, etc.)
│   ├── services/                   # Business logic
│   │   ├── asr_service.py          # Speech recognition (Wav2Vec2)
│   │   ├── ipa_service.py          # IPA phoneme conversion (g2p_en, lru_cache per word)
│   │   ├── gop_service.py          # GOP scoring (CTC log-probs, remainder-aware frames)
│   │   ├── prosody_service.py      # Prosody analysis (pitch via librosa pyin, monotone detection)
│   │   └── pronunciation_service.py # Orchestrator (DP alignment, error types, sub-scores)
│   ├── utils/                      # Pure utility functions
│   │   ├── audio.py                # Audio loading & processing (librosa)
│   │   └── text.py                 # Text normalisation
│   └── application.py              # FastAPI app factory + lifespan model preload
├── tests/                          # pytest + pytest-asyncio (318 tests)
│   ├── conftest.py                 # Shared fixtures (mock services, async client)
│   ├── test_api.py                 # Integration tests for all API endpoints
│   ├── test_audio_utils.py         # Audio loading, normalisation, duration validation
│   ├── test_dependencies.py        # API key auth logic
│   ├── test_gop_service.py         # GOP normalisation, quality levels, scoring
│   ├── test_ipa_service.py         # ARPAbet→IPA mapping, word/text→IPA conversion
│   ├── test_phoneme_mappings.py    # Cross-service phoneme mapping consistency (41 IPA)
│   ├── test_pronunciation_service.py # Alignment, similarity, build IPA result, evaluate
│   ├── test_prosody_service.py     # Prosody scoring, monotone detection, edge cases
│   └── test_text_utils.py          # Text normalisation & tokenisation
├── docs/                           # Project docs
│   ├── workflow.md                 # Request flow & deployment diagrams
│   └── structure.md                # Detailed directory documentation
├── main.py                         # Entry point (reads PORT from Settings)
├── Dockerfile                      # Production image — bakes model at build time
├── railway.toml                    # Railway PaaS deployment config (health check on /health)
├── requirements.txt
├── debugs/                         # Diagnostic & benchmark scripts (not production)
│   ├── benchmark.py                # Per-request resource benchmark (latency, RAM, CPU)
│   ├── debug_gop_raw.py            # Raw GOP score analysis with Google TTS
│   └── verify_scores.py            # Score verification after calibration changes
├── .env.example
└── .github/
    └── copilot-instructions.md     # AI assistant coding conventions
```

## 🔧 Tech Stack

| Component        | Technology                                                                   |
| ---------------- | ---------------------------------------------------------------------------- |
| Web Framework    | FastAPI 0.115+ / Uvicorn                                                     |
| ASR Model        | [Wav2Vec2](https://huggingface.co/facebook/wav2vec2-base-960h) (HuggingFace) |
| IPA Conversion   | g2p_en (grapheme-to-phoneme) + NLTK                                          |
| GOP Scoring      | CTC log-posterior based                                                      |
| Audio Processing | librosa, soundfile, ffmpeg                                                   |
| Validation       | Pydantic v2                                                                  |
| Config           | pydantic-settings (`.env` via absolute path)                                 |
| Logging          | loguru                                                                       |
| Auth             | API Key via `X-API-Key` header                                               |
| Python           | 3.11 (Miniconda)                                                             |

### Supported ASR Models

| Model                                    | Size    | Latency (3s audio, CPU) | WER   | Best for                     |
| ---------------------------------------- | ------- | ----------------------- | ----- | ---------------------------- |
| `facebook/wav2vec2-base-960h`            | ~94 MB  | ~0.25s                  | ~3.4% | Cost-efficient, general use  |
| `facebook/wav2vec2-large-960h-lv60-self` | ~1.2 GB | ~7s                     | ~1.8% | Accented speech (RAM ≥ 4 GB) |

Set via `ASR_MODEL_NAME` in `.env`.

## 🚀 Quick Start

### 1. Install dependencies

```bash
conda create -n pronun python=3.11.7
conda activate pronun
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set API_KEY, model name, etc.
```

### 3. Run the server

```bash
python main.py
# or
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Open API docs

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive Swagger UI.

## 🔐 Authentication

Protected endpoints require an `X-API-Key` header.

| Behaviour          | Condition                                          |
| ------------------ | -------------------------------------------------- |
| Auth **disabled**  | `API_KEY` env var is empty (local dev convenience) |
| `401 Unauthorized` | Header missing when `API_KEY` is set               |
| `403 Forbidden`    | Header present but value doesn't match             |
| ✅ Proceed         | Header matches `API_KEY`                           |

> **Note:** When `API_KEY` is empty, a warning is logged **once at startup** (not per request) to remind you to set it before deploying.

```bash
# Generate a strong key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

| Endpoint                    | Auth Required |
| --------------------------- | ------------- |
| `GET /health`               | ❌ No         |
| `GET /docs`                 | ❌ No         |
| `GET /api/v1/model-info`    | ❌ No         |
| `POST /api/v1/evaluate`     | ✅ Yes        |
| `GET /api/v1/text-analysis` | ✅ Yes        |
| `POST /api/v1/transcribe`   | ✅ Yes        |

## 📡API Endpoints

### `GET /health`

Health check — returns service status and model load state. **No authentication required.**

### `POST /api/v1/evaluate`

Evaluate pronunciation quality. **Requires `X-API-Key` header.**

**Request** (multipart/form-data):

| Field            | Type   | Description                            |
| ---------------- | ------ | -------------------------------------- |
| `audio`          | File   | Audio file (wav, mp3, ogg, flac, webm) |
| `reference_text` | string | Text the speaker should have said      |

> **Upload limit:** Maximum audio file size is **25 MB**. Larger files return HTTP 400.

**Response** (JSON):

```json
{
  "reference_text": "hello world",
  "transcribed_text": "hallo world",
  "results": {
    "reference_ipa": "həloʊ wɝld",
    "actual_ipa": "hɔloʊ wɝld",
    "word_details": [
      {
        "word": "hello",
        "expected_ipa": "həloʊ",
        "actual_ipa": "hɔloʊ",
        "phoneme_details": [
          {
            "expected_ipa": "h",
            "actual_ipa": "h",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 59.34,
            "gop_quality": "fair"
          },
          {
            "expected_ipa": "ə",
            "actual_ipa": "ɔ",
            "is_correct_ipa": false,
            "confidence_ipa": 0,
            "gop_score": 68.51,
            "gop_quality": "good"
          },
          {
            "expected_ipa": "l",
            "actual_ipa": "l",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 71.96,
            "gop_quality": "good"
          },
          {
            "expected_ipa": "oʊ",
            "actual_ipa": "oʊ",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 62.88,
            "gop_quality": "good"
          }
        ],
        "ipa_accuracy": 75,
        "word_gop_score": 65.67,
        "word_gop_quality": "good",
        "error_type": "Mispronunciation"
      },
      {
        "word": "world",
        "expected_ipa": "wɝld",
        "actual_ipa": "wɝld",
        "phoneme_details": [
          {
            "expected_ipa": "w",
            "actual_ipa": "w",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 63.93,
            "gop_quality": "good"
          },
          {
            "expected_ipa": "ɝ",
            "actual_ipa": "ɝ",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 73.6,
            "gop_quality": "good"
          },
          {
            "expected_ipa": "l",
            "actual_ipa": "l",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 50.55,
            "gop_quality": "fair"
          },
          {
            "expected_ipa": "d",
            "actual_ipa": "d",
            "is_correct_ipa": true,
            "confidence_ipa": 1,
            "gop_score": 43.71,
            "gop_quality": "fair"
          }
        ],
        "ipa_accuracy": 100,
        "word_gop_score": 57.95,
        "word_gop_quality": "fair",
        "error_type": "None"
      }
    ],
    "overall_ipa_accuracy": 87.5,
    "overall_gop_score": 61.81,
    "overall_gop_quality": "good"
  },
  "accuracy_score": 75.94,
  "completeness_score": 100.0,
  "fluency_score": 92.5,
  "prosody_score": 78.3,
  "overall_score": 87.48,
  "level": "excellent",
  "feedback": "Excellent pronunciation! Your speech closely matches the reference. Score: 87.5/100."
}
```

### `GET /api/v1/text-analysis`

Analyse English text and convert to IPA with per-word phoneme breakdown. **Requires `X-API-Key` header.**

**Query Parameters:**

| Param  | Type   | Description                           |
| ------ | ------ | ------------------------------------- |
| `text` | string | English text to analyse (1–500 chars) |

**Response** (JSON):

```json
{
  "text": "hello world",
  "ipa": "hɛloʊ wɝld",
  "words": [
    {
      "word": "hello",
      "ipa": "hɛloʊ",
      "phonemes": ["h", "ɛ", "l", "oʊ"]
    },
    {
      "word": "world",
      "ipa": "wɝld",
      "phonemes": ["w", "ɝ", "l", "d"]
    }
  ]
}
```

### `POST /api/v1/transcribe`

Upload audio and get plain-text transcription (no scoring). **Requires `X-API-Key` header.**

**Request** (multipart/form-data):

| Field   | Type | Description                            |
| ------- | ---- | -------------------------------------- |
| `audio` | File | Audio file (wav, mp3, ogg, flac, webm) |

> **Upload limit:** Maximum audio file size is **25 MB**. Larger files return HTTP 400.

**Response** (JSON):

```json
{
  "transcription": "hello world",
  "duration_sec": 2.35
}
```

### `GET /api/v1/model-info`

Return service metadata and capabilities. **No authentication required.**

**Response** (JSON):

```json
{
  "app_name": "Pronunciation Validator",
  "app_version": "1.0.0",
  "asr_model": "facebook/wav2vec2-base-960h",
  "device": "cpu",
  "sample_rate": 16000,
  "max_duration_sec": 30,
  "max_upload_mb": 25,
  "supported_formats": [
    "audio/flac",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/wave",
    "audio/webm",
    "audio/x-wav"
  ]
}
```

## ⚙️ How It Works

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

## 📋 Example cURL

```bash
# Evaluate pronunciation (requires API key)
curl -X POST http://localhost:8000/api/v1/evaluate \
  -H "X-API-Key: your-secret-api-key-here" \
  -F "audio=@recording.wav" \
  -F "reference_text=hello world"

# Text analysis — IPA conversion (requires API key)
curl "http://localhost:8000/api/v1/text-analysis?text=hello+world" \
  -H "X-API-Key: your-secret-api-key-here"

# Transcribe audio only (requires API key)
curl -X POST http://localhost:8000/api/v1/transcribe \
  -H "X-API-Key: your-secret-api-key-here" \
  -F "audio=@recording.wav"

# Model info (public — no API key)
curl http://localhost:8000/api/v1/model-info

# Health check (public — no API key)
curl http://localhost:8000/health
```

## 🐳 Docker

### Standalone

```bash
docker build -t pronunciation-validator .
docker run -p 8000:8000 -e API_KEY=your-key pronunciation-validator
```

Model is **baked into the image** at build time via Dockerfile `RUN` step. PyTorch is installed as **CPU-only** (`torch+cpu` from the PyTorch CPU index) to keep the image lean.

### Railway Deployment

The project includes `railway.toml` for [Railway](https://railway.app) deployment:

- **Dockerfile builder** — model is baked into the image at build time (no persistent volumes)
- **Health check** — `GET /health` with 120s timeout configured in `railway.toml`
- **PORT** is injected by Railway at runtime → read by pydantic-settings natively
- **Build-arg override** — `docker build --build-arg ASR_MODEL_NAME=... .` works correctly (`ENV` set before `RUN`)
- Set `API_KEY`, `ASR_MODEL_NAME`, etc. in Railway Dashboard
- `CMD ["python", "main.py"]` — no shell expansion needed

## ⚙️ Environment Variables

| Variable                    | Default                       | Description                                    |
| --------------------------- | ----------------------------- | ---------------------------------------------- |
| `PORT`                      | `8000`                        | Server port (Railway overrides at runtime)     |
| `ASR_MODEL_NAME`            | `facebook/wav2vec2-base-960h` | HuggingFace model ID                           |
| `ASR_MODEL_CACHE_DIR`       | `./model_cache`               | Model cache directory                          |
| `DEVICE`                    | `cpu`                         | `cpu` or `cuda`                                |
| `API_KEY`                   | _(empty)_                     | Set to enable API key auth                     |
| `CORS_ORIGINS_STR`          | `*`                           | Comma-separated allowed origins (or `*`)       |
| `AUDIO_SAMPLE_RATE`         | `16000`                       | Audio sample rate (Hz)                         |
| `AUDIO_MAX_DURATION_SEC`    | `30`                          | Max audio duration                             |
| `MAX_CONCURRENT_INFERENCES` | `2`                           | Max simultaneous ML inference jobs (semaphore) |
| `DEBUG`                     | `false`                       | Enable uvicorn reload                          |
| `LOG_LEVEL`                 | `INFO`                        | Logging level                                  |

## 🧪 Testing

```bash
pytest tests/ -v
```

**318 tests** across 10 test files, covering all layers:

| Test File                       | Coverage                                                                                                         |
| ------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `test_api.py`                   | Integration tests for all 5 API endpoints                                                                        |
| `test_audio_utils.py`           | Audio loading, normalisation, duration validation, silence detection                                             |
| `test_dependencies.py`          | API key authentication logic                                                                                     |
| `test_gop_service.py`           | GOP normalisation, quality levels, scoring                                                                       |
| `test_ipa_service.py`           | ARPAbet→IPA mapping, word/text→IPA conversion                                                                    |
| `test_phoneme_mappings.py`      | Cross-service phoneme mapping consistency (41 IPA symbols synced across 3 services)                              |
| `test_pronunciation_service.py` | Alignment, similarity, IPA result, error types, completeness, fluency, break detection, prosody, full evaluation |
| `test_prosody_service.py`       | Prosody scoring, monotone detection, contour/variance/range scoring, edge cases                                  |
| `test_text_utils.py`            | Text normalisation & tokenisation                                                                                |
| `conftest.py`                   | Shared fixtures (mock services, async client)                                                                    |

Async tests use `pytest-asyncio` with `asyncio_mode = "auto"`.

## 📊 Resource Benchmarks

| Metric                      | wav2vec2-base-960h | wav2vec2-large |
| --------------------------- | ------------------ | -------------- |
| Model size                  | ~94 MB             | ~1.2 GB        |
| RAM usage                   | ~813 MB            | ~2.5 GB        |
| Latency (3s audio)          | ~0.25s             | ~7s            |
| Est. monthly cost (Railway) | ~$13               | ~$26           |

## 📄 License

MIT
