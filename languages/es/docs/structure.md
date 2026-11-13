<!-- doc-id: docs-structure | lang: es | source-rev: 6c7dadfe -->

> 🌐 **Traducción al español** de [`docs/structure.md`](../../../docs/structure.md) (rev `6c7dadfe`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Estructura del proyecto

> Pronunciation Validation Service — organización de directorios y descripción de los archivos

```
pronunciation-service/
│
├── main.py                     # Entry point — uvicorn bootstrap, reads PORT from Settings
├── requirements.txt            # Pinned Python dependencies (service venv, CPU)
├── pyproject.toml              # Black/Ruff/pytest config
├── Dockerfile                  # Production image — bakes v1 model, downloads v2 files from a private HF repo
├── nixpacks.toml               # Coolify/nixpacks build (same model steps)
├── railway.toml                # Railway config — Dockerfile builder, health check, restart policy
├── download_model.py           # Build-time model download (v1 from HF, v2 from V2_MODEL_REPO)
├── index.html                  # Standalone bilingual (EN/VI) documentation page
├── LICENSE, NOTICE             # Apache-2.0 and third-party credits
├── README.md                   # Overview and quick start
├── .env.example                # Template for .env with all supported variables
├── .dockerignore               # Excludes data/, model_cache/, .env, .venv-train/, ...
├── .github/                    # AI coding assistant rules & project conventions
├── docs/                       # Documentation (see docs/README.md)
├── training/                   # Offline training/export of the v2 models (own CUDA venv)
├── scripts/                    # speechocean762 evaluation harness, sanity set, HF upload
├── debugs/                     # Benchmark (v1 and v2) and diagnostics
├── app/
│   ├── __init__.py
│   ├── application.py          # FastAPI app factory (create_app) + lifespan (model preload)
│   │
│   ├── api/                    # ── API Layer ──
│   │   ├── __init__.py
│   │   ├── dependencies.py     # DI: verify_api_key, get_pronunciation_svc, get_pronunciation_v2_svc (503 if model missing)
│   │   ├── middleware.py       # CORS + rate limit + global exception handlers
│   │   ├── upload.py           # Upload + reference-text validation shared by v1 and v2
│   │   └── routes/
│   │       ├── __init__.py     # Re-exports all routers (health, ipa, model_info,
│   │       │                   #   pronunciation, transcribe)
│   │       ├── health.py       # GET /health — public, no auth
│   │       ├── pronunciation.py# POST /api/v1/evaluate — protected by X-API-Key
│   │       ├── pronunciation_v2.py # POST /api/v2/evaluate — v1 shape + word timing
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
│   │   │                       #   decode(emission) → transcript without a 2nd forward pass
│   │   │                       #   Suppresses masked_spec_embed HF warning
│   │   │                       #   Singleton via @lru_cache → get_asr_service()
│   │   ├── ipa_service.py      # g2p_en text→IPA, _ARPABET_TO_IPA mapping (41 IPA symbols)
│   │   │                       #   _ensure_nltk_data() auto-downloads tagger
│   │   │                       #   Per-word g2p cached via @lru_cache(maxsize=2048)
│   │   │                       #   Singleton via @lru_cache → get_ipa_service()
│   │   ├── gop_service.py      # GOP scoring from CTC log-posteriors
│   │   │                       #   _IPA_TO_WAV2VEC mapping (41 IPA→letter, synced with ipa_service)
│   │   │                       #   score(..., emission=) reuses the orchestrator's emission (one ASR pass per /evaluate)
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
│   │   ├── pronunciation_service.py
│   │                           # Orchestrator — calls ASR → filler filter → IPA → GOP → Prosody
│   │                           #   (_PHONEME_GROUPS, _align_phonemes, level/feedback, error types and break
│   │                           #    detection now live in phoneme_align.py / scoring_rules.py and are re-exported)
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
│   │   ├── phoneme_align.py    # Phone similarity groups + similarity-weighted DP alignment
│   │   │                       #   (torch-free; shared by v1 and v2; max_phonemes argument)
│   │   ├── scoring_rules.py    # Level/feedback text, word error types, break detection
│   │   │                       #   (torch-free; shared by v1 and v2)
│   │   └── v2/                 # ── Phoneme-native pipeline (no torch import) ──
│   │       ├── phone_model.py  # ONNX HuBERT phone CTC → log-posteriors; checks model files exist
│   │       ├── ctc_align.py    # numpy CTC Viterbi forced alignment (parity-tested vs torchaudio)
│   │       ├── gop_features.py # Per-phone GOP features (LPP, LPR, duration), heard phones
│   │       ├── scorer.py       # numpy phone MLP + word/utterance ridge heads (scorer.json)
│   │       ├── analyser.py     # audio + reference text → V2Analysis
│   │       └── pronunciation_v2_service.py  # response assembly, speech gates, score curve
│   │
│   └── utils/                  # ── Pure Utility Functions ──
│       ├── __init__.py
│       ├── audio.py            # load_audio_from_bytes (librosa), normalize, validate duration
│       │                       #   is_silent(waveform, threshold=0.01) — RMS energy check
│       └── text.py             # normalise_text, text_to_words, filter_fillers
│                               #   FILLER_WORDS frozenset (uh, um, hmm, …)
│                               #   Note: normalise_text strips hyphens — avoid hyphenated fillers
│
├── tests/                      # ── Test Suite (pytest + pytest-asyncio, ~460 tests) ──
│   ├── conftest.py             # Shared fixtures (mock services, async client, sample data)
│   ├── test_api.py, test_api_v2.py                 # Endpoint integration tests (v1, v2)
│   ├── test_pronunciation_service.py               # v1 alignment, error types, scores
│   ├── test_pronunciation_v2_service.py            # v2 response assembly, gates, score curve
│   ├── test_v2_ctc_align.py, test_v2_gop_features.py, test_v2_scorer.py,
│   │   test_v2_model_files.py, test_v2_no_torch_import.py   # v2 components
│   ├── test_scoring_sanity.py  # Score bands over tests/sanity_dataset (v1 and v2), noise gate
│   └── ...                     # audio, auth, rate limit, concurrency, IPA/GOP/prosody, metrics
│
└── model_cache/                # Cached HuggingFace model files (git-ignored)
```

## Responsabilidades de cada capa

| Capa            | Ubicación               | Responsabilidad                                             |
| --------------- | ----------------------- | ----------------------------------------------------------- |
| **Entrada**     | `main.py`               | Arranca uvicorn, lee `Settings.port`                        |
| **Fábrica de la app** | `app/application.py` | Construye la app FastAPI, registra los routers, precarga los modelos en lifespan |
| **API**         | `app/api/`              | Rutas, middleware, inyección de dependencias                |
| **Servicios**   | `app/services/`         | Inferencia de ML, puntuación, orquestación                  |
| **Modelos**     | `app/models/schemas.py` | Esquemas Pydantic v2 de petición/respuesta                  |
| **Núcleo**      | `app/core/`             | Ajustes (pydantic-settings), constantes, logging (loguru)   |
| **Utilidades**  | `app/utils/`            | Funciones puras — E/S de audio, procesamiento de texto      |
| **Pruebas**     | `tests/`                | pytest + pytest-asyncio, ~460 pruebas, `asyncio_mode = "auto"` |
| **Entrenamiento** | `training/`           | Entrenamiento/exportación sin conexión de los modelos v2, no lo importa `app/` |
| **Scripts**     | `scripts/`              | Harness de speechocean762, conjunto de sanidad, subida a HF |

## Patrón singleton clave

Cada servicio expone una fábrica `get_*_service()` decorada con `@lru_cache`:

```
get_asr_service()            → ASRService (singleton)
get_ipa_service()            → IPAService (singleton)
get_gop_service()            → GOPService (singleton)
get_prosody_service()        → ProsodyService (singleton)
get_pronunciation_service()  → PronunciationService (singleton, v1)
get_v2_analyser()            → V2Analyser (ONNX model + g2p, singleton)
get_pronunciation_v2_service() → PronunciationV2Service (singleton, v2)
```

Los servicios aceptan dependencias opcionales en `__init__` para facilitar las pruebas — cuando se pasa `None`, recurren al getter del singleton.

## Cadena de configuración

```
.env  ─→  pydantic-settings (absolute path)  ─→  Settings  ─→  get_settings() (@lru_cache)
                                                       │
                                               Used by: services, routes, main.py
```

Variables de entorno importantes: `PORT`, `ASR_MODEL_NAME`, `API_KEY`, `DEVICE`, `LOG_LEVEL`, `DEBUG`, `PHONE_MODEL_DIR`, `PHONE_MODEL_INT8`. Lista completa: [configuration.md](configuration.md).
