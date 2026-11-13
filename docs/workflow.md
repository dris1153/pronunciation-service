<!-- doc-id: docs-workflow | rev: b030953c -->
# Workflow & Request Flow

> Pronunciation Validation Service — how requests flow, how auth works, how deployment is set up.
> Sections 1-2 describe the **v1** pipeline; diagrams for v1 vs v2, a v2 request sequence and startup are in [architecture.md](architecture.md).

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
| 2   | **Input validation**     | `pronunciation.py`     | Check audio content type, file size (≤10 MB) & non-empty reference text                                                                                             |
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

The v1 formulas (accuracy, completeness, fluency, prosody, overall, error types) are in [scoring-v1.md](scoring-v1.md); the phoneme-native v2 scoring is in [scoring-v2.md](scoring-v2.md).

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

Response schemas and examples for every endpoint, v1 and v2: [api.md](api.md).

---

## 9. Resource Benchmarks

Measured latency and memory for v1, v2 FP32 and v2 INT8: [evaluation.md](evaluation.md). Sizing and runtime rules: [deployment.md](deployment.md).
