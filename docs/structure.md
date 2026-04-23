# Project Structure

> Pronunciation Validation Service — directory layout & file descriptions

```
pronuncation-validate/
│
├── main.py                     # Entry point — uvicorn bootstrap, reads PORT from Settings
├── requirements.txt            # Pinned Python dependencies
├── pyproject.toml              # Project metadata, Black/Ruff/pytest config
├── Dockerfile                  # Production image — bakes Wav2Vec2 model at build time
├── railway.toml                # Railway PaaS config — Dockerfile builder, health check, restart policy
├── debugs/                     # Diagnostic & benchmark scripts (not production)
│   ├── benchmark.py            # Per-request resource benchmark (latency, RAM, CPU)
│   ├── debug_gop_raw.py        # Raw GOP score analysis with Google TTS
│   └── verify_scores.py        # Score verification after calibration changes
├── README.md                   # Project overview & quick-start
├── .env                        # Local environment variables (git-ignored)
├── .env.example                # Template for .env with all supported variables
├── .dockerignore               # Excludes model_cache/, .env, __pycache__/, .git/
├── .gitignore                  # Standard Python gitignore
├── .github/
│   └── copilot-instructions.md # AI coding assistant rules & project conventions
├── docs/                       # Project docs
│   ├── workflow.md             # Request flow & deployment diagrams
│   └── structure.md            # Detailed directory documentation
├── app/
│   ├── __init__.py
│   ├── application.py          # FastAPI app factory (create_app) + lifespan (model preload)
│   │
│   ├── api/                    # ── API Layer ──
│   │   ├── __init__.py
│   │   ├── dependencies.py     # DI: verify_api_key (APIKeyHeader), get_pronunciation_svc
│   │   ├── middleware.py       # CORS + global exception handlers (Exception, ValueError)
│   │   └── routes/
│   │       ├── __init__.py     # Re-exports all routers (health, ipa, model_info,
│   │       │                   #   pronunciation, transcribe)
│   │       ├── health.py       # GET /health — public, no auth
│   │       ├── pronunciation.py# POST /api/v1/evaluate — protected by X-API-Key
│   │       ├── ipa.py          # GET /api/v1/text-analysis — text→IPA, protected
│   │       ├── transcribe.py   # POST /api/v1/transcribe — audio→text, protected
│   │       └── model_info.py   # GET /api/v1/model-info — public service metadata
│   │
│   ├── core/                   # ── Core / Config ──
│   │   ├── __init__.py
│   │   ├── config.py           # pydantic-settings Settings class, .env via absolute path
│   │   ├── concurrency.py      # Shared asyncio.Semaphore — limits concurrent ML inference
│   │   │                       #   inference_semaphore() singleton via @lru_cache
│   │   │                       #   max_concurrent_inferences from Settings (default 2)
│   │   │                       #   Extra requests are queued, not rejected
│   │   ├── constants.py        # Shared constants: ALLOWED_AUDIO_TYPES, MAX_UPLOAD_BYTES,
│   │   │                       #   MAX_UPLOAD_MB, SUPPORTED_AUDIO_FORMATS (single source of truth)
│   │   └── logging.py          # loguru setup (sink, format, level from settings)
│   │
│   ├── models/                 # ── Data Models ──
│   │   ├── __init__.py
│   │   └── schemas.py          # All Pydantic v2 schemas: request, response, enums
│   │                           #   PronunciationLevel (enum), ErrorType (enum),
│   │                           #   PhonemeResult (unified phoneme IPA+GOP),
│   │                           #   WordResult (unified word with error_type),
│   │                           #   WordGOP (with start_frame/end_frame timing),
│   │                           #   GOPResult (with sample_rate/total_frames metadata),
│   │                           #   ProsodyResult (pitch stats, monotone flag, prosody_score),
│   │                           #   EvaluationResult, PronunciationResponse
│   │                           #     (accuracy_score, completeness_score, fluency_score,
│   │                           #      prosody_score, overall_score),
│   │                           #   HealthResponse, WordIPADetail, IPAConvertResponse,
│   │                           #   TranscribeResponse, ModelInfoResponse, ErrorResponse
│   │
│   ├── services/               # ── Business Logic ──
│   │   ├── __init__.py
│   │   ├── asr_service.py      # Wav2Vec2 speech-to-text + CTC log-prob extraction
│   │   │                       #   get_ctc_log_probs() → (T, V) for GOP
│   │   │                       #   get_emission() → (1, T, V) for forced alignment
│   │   │                       #   Suppresses masked_spec_embed HF warning
│   │   │                       #   Singleton via @lru_cache → get_asr_service()
│   │   ├── ipa_service.py      # g2p_en text→IPA, _ARPABET_TO_IPA mapping (41 IPA symbols)
│   │   │                       #   _ensure_nltk_data() auto-downloads tagger
│   │   │                       #   Per-word g2p cached via @lru_cache(maxsize=2048)
│   │   │                       #   Singleton via @lru_cache → get_ipa_service()
│   │   ├── gop_service.py      # GOP scoring from CTC log-posteriors
│   │   │                       #   _IPA_TO_WAV2VEC mapping (41 IPA→letter, synced with ipa_service)
│   │   │                       #   score() calls get_emission() once → derives log_probs via squeeze
│   │   │                       #   Silent audio guard (is_silent) short-circuits inference
│   │   │                       #   Forced alignment via torchaudio.functional.forced_align
│   │   │                       #   Falls back to remainder-aware uniform frame segmentation
│   │   │                       #   OOV phonemes receive _FLOOR penalty (not max log-prob)
│   │   │                       #   Per-word timing: start_frame/end_frame populated for fluency
│   │   │                       #   GOPResult includes sample_rate + total_frames metadata
│   │   │                       #   Normalises raw log-probs (−25…−3) → 0–100
│   │   │                       #   Singleton via @lru_cache → get_gop_service()
│   │   ├── prosody_service.py  # Prosody analysis & monotone detection
│   │   │                       #   F0 extraction via librosa.pyin (fmin/fmax from config)
│   │   │                       #   _hz_to_semitones — Hz→semitone conversion relative to array min
│   │   │                       #   _compute_variance_score — pitch CV linear scale (threshold→0, cv_upper→100)
│   │   │                       #   _compute_range_score — semitone range linear scale (0→0, 15st→100)
│   │   │                       #   _compute_contour_score — direction change ratio (target 0.45→100)
│   │   │                       #   _compute_speed_score — words/sec deviation (±0.5 tolerance, 30/wps penalty)
│   │   │                       #   _compute_rhythm_score — nPVI: 30→0, 70→100
│   │   │                       #   prosody_score = 0.55×intonation + 0.20×speed + 0.25×rhythm
│   │   │                       #     intonation = 0.50×variance + 0.30×range + 0.20×contour
│   │   │                       #   Monotone detection: CV < threshold (0.08) → cap score at 30
│   │   │                       #   Voiced ratio guard: <10% voiced → score 0
│   │   │                       #   Singleton via @lru_cache → get_prosody_service()
│   │   └── pronunciation_service.py
│   │                           # Orchestrator — calls ASR → filler filter → IPA → GOP → Prosody
│   │                           #   filter_fillers() + text_to_words() applied consistently
│   │                           #   _PHONEME_GROUPS (11 groups, 41 IPA, synced with above)
│   │                           #   _align_words (plain Levenshtein) + _align_phonemes
│   │                           #     (phonetic similarity costs, float64, ε=1e-6)
│   │                           #   _detect_error_type() → None/Mispronunciation/Omission/
│   │                           #     Insertion/UnexpectedBreak/MissingBreak
│   │                           #   _compute_completeness() → accuracy-weighted ratio of
│   │                           #     correctly pronounced ref words (accuracy ≥ 60%)
│   │                           #   _compute_fluency() → speech rate + pause analysis
│   │                           #   _detect_unexpected_breaks() → word indices with >0.8s gaps
│   │                           #   _detect_missing_breaks() → word indices missing pause at
│   │                           #     punctuation boundaries (<0.15s gap)
│   │                           #   accuracy_score = 55 % IPA + 45 % GOP
│   │                           #   completeness_score = correctly pronounced / ref words × 100
│   │                           #   fluency_score = 0.4 × rate + 0.6 × pause (ideal 3.0 wps)
│   │                           #   prosody_score from ProsodyService.analyse()
│   │                           #   overall = sort 4 sub-scores → 0.4×s0+0.2×s1+0.2×s2+0.2×s3
│   │                           #   Singleton via @lru_cache → get_pronunciation_service()
│   │
│   └── utils/                  # ── Pure Utility Functions ──
│       ├── __init__.py
│       ├── audio.py            # load_audio_from_bytes (librosa), normalize, validate duration
│       │                       #   is_silent(waveform, threshold=0.01) — RMS energy check
│       └── text.py             # normalise_text, text_to_words, filter_fillers
│                               #   FILLER_WORDS frozenset (uh, um, hmm, …)
│                               #   Note: normalise_text strips hyphens — avoid hyphenated fillers
│
├── tests/                      # ── Test Suite (pytest + pytest-asyncio, 318 tests) ──
│   ├── __init__.py
│   ├── conftest.py             # Shared fixtures (mock services, async client, sample data)
│   ├── test_api.py             # Integration tests for all 5 API endpoints
│   ├── test_audio_utils.py     # Audio loading, normalisation, duration validation
│   ├── test_dependencies.py    # API key auth (disabled, 401, 403, success)
│   ├── test_gop_service.py     # GOP normalisation, quality levels, full scoring
│   ├── test_ipa_service.py     # ARPAbet mapping, word→IPA, text→IPA conversion
│   ├── test_phoneme_mappings.py # Cross-service mapping consistency (41 IPA symbols,
│   │                           #   _ARPABET_TO_IPA ↔ _IPA_TO_WAV2VEC ↔ _PHONEME_GROUPS)
│   ├── test_pronunciation_service.py # Alignment, similarity, error types, completeness,
│   │                           #   fluency, break detection, prosody, evaluation
│   ├── test_prosody_service.py # Prosody scoring, monotone detection, contour/variance/range,
│   │                           #   voiced ratio guard, edge cases
│   └── test_text_utils.py      # Text normalisation & tokenisation
│
└── model_cache/                # Cached HuggingFace model files (git-ignored)
```

## Layer Responsibilities

| Layer           | Location                | Responsibility                                              |
| --------------- | ----------------------- | ----------------------------------------------------------- |
| **Entry**       | `main.py`               | Bootstrap uvicorn, read `Settings.port`                     |
| **App Factory** | `app/application.py`    | Build FastAPI app, register routers, lifespan model preload |
| **API**         | `app/api/`              | Routes, middleware, dependency injection                    |
| **Services**    | `app/services/`         | ML inference, scoring, orchestration                        |
| **Models**      | `app/models/schemas.py` | Pydantic v2 request/response schemas                        |
| **Core**        | `app/core/`             | Settings (pydantic-settings), constants, logging (loguru)   |
| **Utils**       | `app/utils/`            | Pure functions — audio I/O, text processing                 |
| **Tests**       | `tests/`                | pytest + pytest-asyncio, 318 tests, `asyncio_mode = "auto"` |

## Key Singleton Pattern

Every service exposes a `get_*_service()` factory decorated with `@lru_cache`:

```
get_asr_service()            → ASRService (singleton)
get_ipa_service()            → IPAService (singleton)
get_gop_service()            → GOPService (singleton)
get_prosody_service()        → ProsodyService (singleton)
get_pronunciation_service()  → PronunciationService (singleton)
```

Services accept optional dependencies in `__init__` for testability — when `None` is passed, they fall back to the singleton getter.

## Configuration Chain

```
.env  ─→  pydantic-settings (absolute path)  ─→  Settings  ─→  get_settings() (@lru_cache)
                                                       │
                                               Used by: services, routes, main.py
```

Important env vars: `PORT`, `ASR_MODEL_NAME`, `API_KEY`, `DEVICE`, `LOG_LEVEL`, `DEBUG`.
