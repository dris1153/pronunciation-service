# Workflow & Request Flow

> Pronunciation Validation Service — how requests flow, how auth works, how deployment is set up

---

## 1. Architecture Overview

```
┌──────────┐     ┌──────────────────────┐      ┌─────────────────────────┐
│  Client  │────▶│   FastAPI API         │────▶│  PronunciationService   │
│ (audio + │     │  /api/v1/evaluate     │      │  (orchestrator)         │
│  text)   │     │  /api/v1/text-analysis│      └──┬──────┬──────┬──────┬─┘
└──────────┘     │  /api/v1/transcribe   │         │      │      │      │
                 │  /api/v1/model-info   │         ▼      ▼      ▼      ▼
                 └──────────────────────┘    ┌──────┐ ┌────┐ ┌────┐ ┌───────┐
                                             │  ASR │ │IPA │ │GOP │ │Prosody│
                                             │  Svc │ │Svc │ │Svc │ │  Svc  │
                                             └──┬───┘ └──┬─┘ └──┬─┘ └───┬───┘
                                                │        │      │       │
                                           Wav2Vec2   g2p_en  CTC    librosa
                                           model     + NLTK  log-    pyin
                                                             posts
```

---

## 2. Request Flow (POST /api/v1/evaluate)

```
Client                  FastAPI                PronunciationService        ASR / IPA / GOP
  │                       │                           │                          │
  │── POST audio+text ──▶ │                          │                          │
  │   + X-API-Key header  │                           │                          │
  │                       │── verify_api_key() ──▶ ✓ │                          │
  │                       │── validate audio type     │                          │
  │                       │── read audio bytes        │                          │
  │                       │                           │                          │
  │                       │── svc.evaluate() ────────▶│                         │
  │                       │                           │── load_audio_from_bytes()
  │                       │                           │── validate_audio_duration()
  │                       │                           │── normalize_audio()      │
  │                       │                           │                          │
  │                       │                           │── asr.get_emission() ─▶ │ Wav2Vec2 (1 pass)
  │                       │                           │◀── emission ─────────── │
  │                       │                           │── asr.decode(emission)   │
  │                       │                           │   → transcription        │
  │                       │                           │                          │
  │                       │                           │── ipa.to_ipa() ───────▶ │ g2p_en
  │                       │                           │◀── ref_ipa + act_ipa ── │
  │                       │                           │── compare phonemes       │
  │                       │                           │                          │
  │                       │                           │── gop.score(emission) ▶ │ reuses emission
  │                       │                           │◀── gop_result ───────── │
  │                       │                           │                         │
  │                       │                           │── combined_score        │
  │                       │                           │   accuracy = 0.55×IPA   │
  │                       │                           │            + 0.45×GOP   │
  │                       │                           │   completeness =        │
  │                       │                           │     accuracy-weighted   │
  │                       │                           │     ratio of ref words  │
  │                       │                           │   fluency = 0.4×rate    │
  │                       │                           │          + 0.6×pause    │
  │                       │                           │   prosody = 0.55×int    │
  │                       │                           │     + 0.20×spd+0.25×rhy│
  │                       │                           │   overall = 0.4×s0      │
  │                       │                           │    + 0.2×s1+0.2×s2     │
  │                       │                           │          + 0.2×s3       │
  │                       │                           │── error_type per word   │
  │                       │                           │   (+ break detection)   │
  │                       │                           │── level + feedback      │
  │                       │                          │                          │
  │                       │◀── PronunciationResponse ─│                         │
  │◀── JSON response ────│                           │                          │
```

### Step-by-step

| #   | Step                     | Component              | Description                                                                                                                                                         |
| --- | ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Auth**                 | `dependencies.py`      | Validate `X-API-Key` header (skip if `API_KEY` is empty)                                                                                                            |
| 2   | **Input validation**     | `pronunciation.py`     | Check audio content type, file size (≤25 MB) & non-empty reference text                                                                                             |
| 3   | **Audio loading**        | `utils/audio.py`       | Decode audio bytes → 16 kHz mono float32 numpy array (librosa)                                                                                                      |
| 4   | **Transcription**        | `ASRService`           | Wav2Vec2 model produces text from speech                                                                                                                            |
| 5   | **Filler filtering**     | `utils/text.py`        | Strip disfluency words (uh, um, hmm…) via `filter_fillers(text_to_words(...))`                                                                                      |
| 6   | **IPA conversion**       | `IPAService`           | Both reference text and transcription → IPA phoneme sequences                                                                                                       |
| 7   | **IPA comparison**       | `PronunciationService` | Align & compare expected vs actual phonemes, calculate accuracy                                                                                                     |
| 8   | **GOP scoring**          | `GOPService`           | Silent check → CTC log-posteriors → forced alignment → per-phoneme GOP + timing                                                                                     |
| 9   | **Prosody analysis**     | `ProsodyService`       | Pitch extraction (pyin) → variance, range, contour scoring → monotone detection                                                                                     |
| 10  | **Error classification** | `PronunciationService` | Per-word error type: None / Mispronunciation / Omission / Insertion / UnexpectedBreak / MissingBreak                                                                |
| 11  | **Sub-scores**           | `PronunciationService` | `accuracy_score` = 55% IPA + 45% GOP; `completeness_score` = accuracy-weighted ratio; `fluency_score` = rate + pause; `prosody_score` = intonation + speed + rhythm |
| 12  | **Final scoring**        | `PronunciationService` | Overall = 0.4×s0 + 0.2×s1 + 0.2×s2 + 0.2×s3 (4 sub-scores sorted low→high)                                                                                          |
| 13  | **Response**             | `pronunciation.py`     | Return `PronunciationResponse` JSON with level & feedback                                                                                                           |

---

### v2 request flow (POST /api/v2/evaluate)

Same validation, auth, rate limit and inference semaphore as v1 (`app/api/upload.py`), then, with no torch involved:
audio decode → ONNX phone CTC (20 ms frames) → numpy CTC forced alignment → per-phone GOP features + heard phones → learned scorer
(phone MLP → word/utterance ridge) → v1-shaped response with word timing. Break errors reuse the v1 pause rules on the aligned word spans.

## 3. Authentication Flow

```
Request with X-API-Key header
            │
            ▼
   ┌─── API_KEY set? ───┐
   │                     │
   No                   Yes
   │                     │
   ▼                     ▼
 SKIP auth        ┌── Header present? ──┐
 (dev mode)       │                     │
                  No                   Yes
                  │                     │
                  ▼                     ▼
              401 Unauthorized    ┌── Key matches? ──┐
                                  │                   │
                                  No                 Yes
                                  │                   │
                                  ▼                   ▼
                              403 Forbidden       ✅ Proceed
```

| Endpoint                    | Auth Required                        |
| --------------------------- | ------------------------------------ |
| `GET /health`               | ❌ No — public for health checks     |
| `GET /docs`                 | ❌ No — Swagger UI                   |
| `GET /redoc`                | ❌ No — ReDoc UI                     |
| `GET /api/v1/model-info`    | ❌ No — public service metadata      |
| `POST /api/v1/evaluate`     | ✅ Yes — requires `X-API-Key` header |
| `GET /api/v1/text-analysis` | ✅ Yes — requires `X-API-Key` header |
| `POST /api/v1/transcribe`   | ✅ Yes — requires `X-API-Key` header |

---

## 4. Application Startup (Lifespan)

```
uvicorn starts
    │
    ▼
create_app()
    │── configure FastAPI (title, version, docs)
    │── register_middleware (CORS, exception handlers)
    │── include_router (health, pronunciation, ipa, transcribe, model_info)
    │
    ▼
lifespan() — async context manager
    │── setup_logging()
    │── get_settings()           ← load .env via absolute path
    │── check ffmpeg available   ← needed for MP3/OGG/WebM decoding
    │── get_asr_service()        ← download/load Wav2Vec2 model
    │── get_ipa_service()        ← init g2p_en + NLTK data
    │── get_gop_service()        ← init GOP scorer
    │── get_prosody_service()    ← init prosody analyser
    │── log "All models loaded ✓"
    │
    ▼
Application is ready to serve requests
    │
    ▼ (on shutdown)
    └── log "Shutting down …"
```

---

## 5. Deployment Flows

### 5a. Railway (Production)

```
git push to Railway
    │
    ▼
Railway reads railway.toml
    │── builder = "dockerfile"
    │── healthcheckPath = "/health"
    │── healthcheckTimeout = 120
    │── restartPolicyType = "on_failure"
    │
    ▼
Docker build
    │── python:3.11-slim base
    │── install ffmpeg, libsndfile1
    │── pip install CPU-only PyTorch (torch+cpu from PyTorch CPU index)
    │── pip install requirements.txt
    │── ENV ASR_MODEL_NAME (set before RUN — build-arg override works)
    │── BAKE Wav2Vec2 model into image  ← no persistent volumes on Railway
    │── ENV PORT=8000 (default; Railway overrides at runtime)
    │
    ▼
CMD ["python", "main.py"]
    │── pydantic-settings reads PORT env var → Settings.port
    │── uvicorn binds to 0.0.0.0:$PORT
    │
    ▼
Railway health check → GET /health
    │── Returns { status: "ok", version, model_loaded }
```

**Key points:**

- Railway injects `PORT` at runtime — pydantic-settings reads it natively (no shell `$PORT` expansion)
- Model is **baked** into the Docker image at build time (Railway has no persistent volumes)
- `ENV ASR_MODEL_NAME` is set **before** the `RUN` model-download step so `--build-arg` overrides work
- Environment variables (`API_KEY`, `ASR_MODEL_NAME`, etc.) are set in Railway Dashboard
- `railway.toml` has `healthcheckPath = "/health"` and `healthcheckTimeout = 120`
- No `startCommand` — CMD from Dockerfile is used directly

---

## 6. Scoring System

### Accuracy Score

The `accuracy_score` combines IPA phoneme accuracy and GOP scoring:

### IPA Accuracy (55% of accuracy_score)

```
Reference text  ──▶  g2p_en  ──▶  IPA phonemes (expected)
                                        │
Transcription   ──▶  g2p_en  ──▶  IPA phonemes (actual)
                                        │
                                   Compare & align
                                        │
                                   accuracy = matched / total
```

### GOP Score (45% of accuracy_score)

```
Audio waveform  ──▶  is_silent()?  ──yes──▶  zero GOP scores (skip inference)
                          │
                          no
                          │
                     Wav2Vec2  ──▶  CTC log-posteriors (1, T, V)  [get_emission()]
                                        │
                              squeeze to (T, V) for _compute_phoneme_gop
                                        │
Reference text  ──▶  IPA  ──▶  Wav2Vec2 vocab tokens
                                        │
                      torchaudio.functional.forced_align  ──▶  phoneme boundaries
                         (falls back to uniform segmentation if OOV / too short)
                                        │
                              OOV phonemes → _FLOOR penalty (0 %)
                                        │
                              Per-phoneme log-prob mean
                                        │
                              Normalises raw log-probs (−25…−3) → 0–100
```

### Combined Score

```
accuracy_score     = 0.55 × ipa_accuracy + 0.45 × gop_score
completeness_score = accuracy-weighted ratio of correctly pronounced ref words
                     (only words with IPA accuracy ≥ 60% count as "complete")
fluency_score      = 0.4 × rate_score + 0.6 × pause_score
                     (rate: deviation from 3.0 wps, pause: gaps >0.8s penalised)
prosody_score      = 0.55 × intonation + 0.20 × speed + 0.25 × rhythm
                     (intonation = 0.50×variance + 0.30×range + 0.20×contour)
                     (speed: deviation from 3.0 wps, rhythm: nPVI)
                     (monotone cap at 30)
overall_score      = 0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3 (sorted low→high)
```

### Word-Level Error Types

Each word in the evaluation receives an `error_type`:

| Condition                                  | ErrorType          |
| ------------------------------------------ | ------------------ |
| Aligned (match/substitute), accuracy ≥ 60% | `None`             |
| Aligned (match/substitute), accuracy < 60% | `Mispronunciation` |
| Word in reference but not spoken (delete)  | `Omission`         |
| Word spoken but not in reference (insert)  | `Insertion`        |
| Long pause (>0.8s) detected before word    | `UnexpectedBreak`  |
| Missing pause at punctuation (<0.15s)      | `MissingBreak`     |

| Score Range | Level        | Feedback                       |
| ----------- | ------------ | ------------------------------ |
| 80–100      | 🟢 Excellent | Closely matches reference      |
| 60–79       | 🔵 Good      | Minor improvements needed      |
| 40–59       | 🟡 Fair      | Several sounds need practice   |
| 0–39        | 🔴 Poor      | Significant improvement needed |

---

## 7. Supported Audio Formats

| Format | MIME Types                               |
| ------ | ---------------------------------------- |
| WAV    | `audio/wav`, `audio/x-wav`, `audio/wave` |
| MP3    | `audio/mpeg`, `audio/mp3`                |
| OGG    | `audio/ogg`                              |
| FLAC   | `audio/flac`                             |
| WebM   | `audio/webm`                             |

All audio is converted to **16 kHz mono float32** numpy arrays via librosa.

---

## 8. API Response Schema

### POST /api/v1/evaluate — `PronunciationResponse`

```json
{
  "reference_text": "hello world",
  "transcribed_text": "hello world",
  "results": {
    "reference_ipa": "hɛloʊ wɝld",
    "actual_ipa": "hɛloʊ wɝld",
    "word_details": [
      {
        "word": "hello",
        "expected_ipa": "hɛloʊ",
        "actual_ipa": "hɛloʊ",
        "phoneme_details": [
          {
            "expected_ipa": "h",
            "actual_ipa": "h",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 88.2,
            "gop_quality": "excellent"
          },
          {
            "expected_ipa": "ɛ",
            "actual_ipa": "ɛ",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 75.1,
            "gop_quality": "good"
          }
        ],
        "ipa_accuracy": 100.0,
        "word_gop_score": 81.6,
        "word_gop_quality": "excellent",
        "error_type": "None"
      }
    ],
    "overall_ipa_accuracy": 100.0,
    "overall_gop_score": 82.5,
    "overall_gop_quality": "excellent"
  },
  "accuracy_score": 90.4,
  "completeness_score": 100.0,
  "fluency_score": 95.0,
  "prosody_score": 78.3,
  "overall_score": 94.2,
  "level": "excellent",
  "feedback": "Excellent pronunciation! Your speech closely matches the reference. Score: 94.2/100."
}
```

### GET /api/v1/text-analysis — `IPAConvertResponse`

```json
{
  "text": "hello world",
  "ipa": "hɛloʊ wɝld",
  "words": [
    { "word": "hello", "ipa": "hɛloʊ", "phonemes": ["h", "ɛ", "l", "oʊ"] },
    { "word": "world", "ipa": "wɝld", "phonemes": ["w", "ɝ", "l", "d"] }
  ]
}
```

### POST /api/v1/transcribe — `TranscribeResponse`

```json
{
  "transcription": "hello world",
  "duration_sec": 2.35
}
```

### GET /api/v1/model-info — `ModelInfoResponse`

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

### GET /health — `HealthResponse`

```json
{
  "status": "ok",
  "version": "1.0.0",
  "model_loaded": true
}
```

---

## 9. Resource Benchmarks

| Metric             | Value (wav2vec2-base-960h) |
| ------------------ | -------------------------- |
| Model size         | ~94 MB                     |
| RAM usage          | ~813 MB                    |
| Latency (3s audio) | ~0.25 s on CPU             |
| Estimated cost     | ~$13/month (Railway Hobby) |

For non-native speaker evaluation with higher accuracy, use `wav2vec2-large-960h-lv60-self` (~1.2 GB, ~7s latency, WER ~1.8%).
