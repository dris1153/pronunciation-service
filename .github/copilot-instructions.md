# Copilot Instructions — Pronunciation Validation Service

## Architecture Overview

Layered FastAPI service: **API → Service → Model/Utils**. The evaluation pipeline flows:
`Audio bytes → ASR (Wav2Vec2) → Transcription → IPA comparison + GOP scoring + Prosody analysis + Error classification → Unified response`

- **`app/api/`** — FastAPI routes, middleware, DI via `dependencies.py`. Routes in `routes/` sub-package.
  - `dependencies.py` — Houses `verify_api_key` (API key auth) and `get_pronunciation_svc` (service DI).
  - `routes/health.py` — `GET /health` — public, no auth.
  - `routes/pronunciation.py` — `POST /api/v1/evaluate` — full pronunciation evaluation (IPA + GOP).
  - `routes/ipa.py` — `GET /api/v1/text-analysis` — text → IPA conversion with per-word phoneme breakdown.
  - `routes/transcribe.py` — `POST /api/v1/transcribe` — audio → plain-text transcription only (no scoring).
  - `routes/model_info.py` — `GET /api/v1/model-info` — public service metadata (model, device, limits, formats).
- **`app/services/`** — Business logic. Four domain services + one orchestrator:
  - `asr_service.py` — Wav2Vec2 speech-to-text & CTC log-prob extraction. Exposes two methods: `get_ctc_log_probs()` → `(T, V)` for general use; `get_emission()` → `(1, T, V)` batched form for `torchaudio.functional.forced_align`. Suppresses HuggingFace warning about `masked_spec_embed` via `warnings.catch_warnings()`.
  - `ipa_service.py` — Text → IPA phonemes via `g2p_en` (ARPAbet→IPA mapping). Per-word g2p result cached via `_run_g2p()` with `@lru_cache(maxsize=2048)`.
  - `gop_service.py` — GOP scoring from CTC log-posteriors. `score()` calls `get_emission()` once and derives `log_probs = emission.squeeze(0)` to avoid duplicating log-softmax work. Silent audio guard: `is_silent(waveform)` short-circuits all inference and returns zero-score results. Forced alignment via `torchaudio.functional.forced_align` (remainder-aware uniform segmentation fallback). OOV phonemes receive `_FLOOR` penalty. Per-word timing data (`start_frame`, `end_frame`) and metadata (`sample_rate`, `total_frames`) are populated for fluency analysis.
  - `prosody_service.py` — Prosody analysis & monotone detection via `librosa.pyin`. Extracts F0 (fundamental frequency) with configurable `fmin`/`fmax` from settings. Scoring: `prosody_score = 0.55 × intonation + 0.20 × speed + 0.25 × rhythm`. Intonation score uses pitch coefficient of variation (CV = std/mean); CV below `monotone_threshold` (0.08) → `is_monotone = True`, score capped at 30. Range score uses semitone range (0→0, 15 st→100). Contour score uses direction change ratio (target 0.45). Speed score uses words-per-second deviation from ideal 3.0 wps (±0.5 tolerance), penalty 30 per wps. Rhythm score uses normalised Pairwise Variability Index (nPVI); native English nPVI ~50–70. nPVI scored linearly: 30→0, 70→100. Voiced ratio guard: <10% voiced frames → score 0. Returns `ProsodyResult` with all pitch statistics. Singleton via `@lru_cache` → `get_prosody_service()`.
  - `pronunciation_service.py` — Orchestrates the above four; strips filler words via `filter_fillers(text_to_words(raw_transcription))` (consistent normalisation pipeline); computes sub-scores (`accuracy_score` = 55% IPA + 45% GOP, `completeness_score` = accuracy-weighted ratio of correctly pronounced reference words, `fluency_score` = speech rate + pause analysis from CTC frame timing, `prosody_score` from ProsodyService) and overall score (sort 4 sub-scores, `0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3` — Azure PronScore formula). Two separate DP alignment functions: `_align_words()` (plain Levenshtein) and `_align_phonemes()` (phonetic similarity costs with 0.85 substitution cost for similar phonemes, capped at `_MAX_ALIGN_PHONEMES = 200`). Both use `float64` precision with `_EPS = 1e-6` back-trace tolerance. Phoneme similarity partial credit: 0.3 for same-group phonemes (conservative, aligned with Azure). Word-level error classification via `_detect_error_type()` (None/Mispronunciation/Omission/Insertion). Fluency via `_compute_fluency(gop_result)` (counts spoken words from frame timing). Break detection via `_detect_unexpected_breaks()` — overrides error type with `UnexpectedBreak` when long pauses (>0.8s) are detected between words. Missing break detection via `_detect_missing_breaks(gop_result, raw_reference)` — overrides error type with `MissingBreak` when user should have paused at punctuation boundaries (`,`, `.`, `;`, `:`, `?`, `!`) but gap < 0.15s. Completeness via `_compute_completeness()` — only words with accuracy ≥ `_MISPRONUNCIATION_THRESHOLD` count as correctly pronounced.
- `app/models/schemas.py` — All Pydantic v2 request/response schemas in one file. Includes `ErrorType` enum (None, Mispronunciation, Omission, Insertion, UnexpectedBreak, MissingBreak), `WordResult` with `error_type` field, `WordGOP` with `start_frame`/`end_frame` timing, `GOPResult` with `sample_rate`/`total_frames` metadata, `ProsodyResult` with pitch statistics and monotone flag, `PronunciationResponse` with `accuracy_score`, `completeness_score`, `fluency_score`, and `prosody_score` sub-scores. Also includes `WordIPADetail`, `IPAConvertResponse`, `TranscribeResponse`, `ModelInfoResponse` for the auxiliary endpoints.
- **`app/core/`** — Settings (`pydantic-settings` from `.env` via absolute path), loguru logging setup, shared constants
  - `constants.py` — Single source of truth for audio upload limits (`MAX_UPLOAD_BYTES`, `MAX_UPLOAD_MB`) and MIME types (`ALLOWED_AUDIO_TYPES`, `SUPPORTED_AUDIO_FORMATS`). Used by route validation and `/model-info`.
  - `concurrency.py` — Shared `asyncio.Semaphore` via `inference_semaphore()` (singleton, `@lru_cache`). Limits concurrent ML inference jobs to `Settings.max_concurrent_inferences` (default 2). Extra requests are **queued**, not rejected. Used by `/evaluate` and `/transcribe`.
- **`app/utils/`** — Pure functions for audio I/O (`librosa`) and text normalisation
  - `audio.py` — `load_audio_from_bytes`, `normalize_audio`, `validate_audio_duration`, `is_silent(waveform, threshold=0.01)` — RMS energy silence check. Use before expensive ML inference.
  - `text.py` — `normalise_text`, `text_to_words`, `filter_fillers`. `FILLER_WORDS` frozenset contains only forms that survive `normalise_text` (no hyphens — the regex `[^a-z0-9\s']` strips them).
- **`app/application.py`** — App factory (`create_app()`) with lifespan that pre-loads all ML models

## Key Patterns

### Singleton services via `@lru_cache`

Every service has a `get_*_service()` function decorated with `@lru_cache` that returns a singleton. Services accept optional dependencies in `__init__` for testability:

```python
class GOPService:
    def __init__(self, asr: ASRService | None = None, ipa: IPAService | None = None):
        self._asr = asr or get_asr_service()
```

### Configuration

All settings come from `app/core/config.py` → `Settings(BaseSettings)` loaded from `.env`. The `.env` path is resolved as an absolute path: `Path(__file__).resolve().parent.parent.parent / ".env"` — never a relative path. Access via `get_settings()`.

Key vars: `ASR_MODEL_NAME`, `DEVICE`, `AUDIO_SAMPLE_RATE`, `API_KEY`, `MAX_CONCURRENT_INFERENCES`.

### API Key Authentication

- `app/api/dependencies.py` exposes `verify_api_key` dependency using `APIKeyHeader(name="X-API-Key")`.
- When `API_KEY` env var is empty → enforcement is disabled (local dev convenience).
- When set → missing header returns **401**, wrong value returns **403**.
- Applied via `Depends(verify_api_key)` on protected routes (e.g., `POST /api/v1/evaluate`, `GET /api/v1/text-analysis`, `POST /api/v1/transcribe`).
- `/health` and `/api/v1/model-info` endpoints are **not** protected — must remain public.

### Phoneme mappings are critical data

- `ipa_service.py` contains `_ARPABET_TO_IPA` (ARPAbet → IPA) — used for text→IPA conversion
- `gop_service.py` contains `_IPA_TO_WAV2VEC` (IPA → Wav2Vec2 vocab tokens) — used for GOP scoring
- `pronunciation_service.py` contains `_PHONEME_GROUPS` (IPA phoneme similarity groups) — used for confidence scoring
- All three mappings cover exactly **41 IPA symbols** and **must stay in sync**
- When adding new phonemes, update all three mappings

### NLTK data auto-download

`ipa_service.py` has `_ensure_nltk_data()` that auto-downloads `averaged_perceptron_tagger_eng` before `g2p_en` init. If adding new NLTK-dependent features, follow this pattern.

### Word-level error classification

`pronunciation_service.py` exposes `_detect_error_type(alignment_op, word_accuracy) → ErrorType`:

- `delete` op → `ErrorType.OMISSION` (word in reference but not spoken)
- `insert` op → `ErrorType.INSERTION` (word spoken but not in reference)
- accuracy < `_MISPRONUNCIATION_THRESHOLD` (60.0) → `ErrorType.MISPRONUNCIATION`
- accuracy ≥ 60.0 → `ErrorType.NONE`

Additionally, `_detect_unexpected_breaks(gop_result) → set[int]` analyses word-level CTC frame timing to detect long pauses (>0.8s) between consecutive words. When a break is detected before a word, its error type is overridden to `ErrorType.UNEXPECTED_BREAK` (unless the word already has a worse error like Omission/Insertion).

Similarly, `_detect_missing_breaks(gop_result, raw_reference) → set[int]` uses `_find_expected_break_positions(raw_reference)` to locate punctuation boundaries (`,`, `.`, `;`, `:`, `?`, `!`) and checks whether the speaker paused at least `_MISSING_BREAK_SEC` (0.15s). Returns word indices where the gap was too short; error type is overridden to `ErrorType.MISSING_BREAK` only when the current error is `ErrorType.NONE`.

Threshold `60.0` is aligned with Azure Speech SDK. Defined as `_MISPRONUNCIATION_THRESHOLD` constant.

### Scoring formula (calibrated to Azure Speech SDK)

Four-tier scoring system:

1. **`accuracy_score`** = `0.55 × IPA_accuracy + 0.45 × GOP_score` — phoneme-level pronunciation quality. GOP normalised from raw log-probs (empirical range −25…−3) to 0–100 scale. Phoneme similarity partial credit = 0.3 for same-group phonemes; DP substitution cost = 0.85 for similar phonemes.
2. **`completeness_score`** = `correctly_pronounced_ref_words / total_ref_words × 100` — via `_compute_completeness(word_ops, ref_word_count, word_accuracies)`. Only words with accuracy ≥ `_MISPRONUNCIATION_THRESHOLD` (60.0) count as "correctly pronounced" — aligned with Azure's definition where merely attempting a word is insufficient.
3. **`fluency_score`** = `0.4 × rate_score + 0.6 × pause_score` — via `_compute_fluency(gop_result)`. Pause-dominant weighting matches Azure's definition ("silent breaks between words"). Speech rate scored against ideal 3.0 wps (±0.5 tolerance), pause penalty for gaps >0.8s between words.
4. **`prosody_score`** = `0.55 × intonation + 0.20 × speed + 0.25 × rhythm` — via `ProsodyService.analyse(waveform, sr, word_durations, total_duration)`. Covers all four Azure dimensions:
   - **Intonation** (55%) = `0.50 × variance + 0.30 × range + 0.20 × contour` — pitch CV (threshold 0.08, upper 0.25), semitone range (0→0, 15 st→100), direction changes (target ratio 0.45).
   - **Speed** (20%) = `_compute_speed_score(word_durations, total_duration)` — deviation from ideal 3.0 wps (±0.5 tolerance), penalty 30 per wps deviation.
   - **Rhythm** (25%) = `_compute_rhythm_score(word_durations)` — normalised Pairwise Variability Index (nPVI). Measures stress-timing naturalness; native English nPVI ~50–70, syllable-timed ~30–40. Scored linearly: nPVI 30→0, nPVI 70→100.
   - When `word_durations` is `None` (no CTC timing available), speed and rhythm default to 50 (neutral).
   - Monotone cap: `is_monotone → prosody_score ≤ 30`.
5. **`overall_score`** = sort 4 sub-scores low→high, then `0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3` — Azure PronScore formula (scripted, with prosody). Heavily penalises weakest dimension.

### HuggingFace warning suppression

`asr_service.py` wraps `Wav2Vec2ForCTC.from_pretrained()` in `warnings.catch_warnings()` to suppress the `"Some weights of Wav2Vec2ForCTC were not initialized"` message about `masked_spec_embed`. This weight is only used during training and is irrelevant for inference.

## Deployment

### Railway

- Config: `railway.toml` — uses Dockerfile builder, health check on `/health`, 120s timeout.
- Railway injects `$PORT` at runtime — pydantic-settings reads it natively into `Settings.port`.
- `CMD ["python", "main.py"]` — uvicorn binds to `Settings.port`, no shell expansion needed.
- Model is **baked into the Docker image** at build time (Railway has no persistent volumes).
- Dockerfile sets `ENV ASR_MODEL_NAME` **before** the `RUN` model-download step so `--build-arg` overrides work correctly.
- Environment variables are set in Railway Dashboard (never shipped in `.env` inside the image).
- `.dockerignore` excludes `model_cache/`, `.env`, `__pycache__/`, `.git/` from build context.

### Model selection

Two models are supported — controlled via `ASR_MODEL_NAME` env var:

- `facebook/wav2vec2-base-960h` — ~94 MB, fast inference (~2s/3s audio on CPU), WER ~3.4%
- `facebook/wav2vec2-large-960h-lv60-self` — ~1.2 GB, slower (~7s/3s audio on CPU), WER ~1.8%, better for accented speech

For pronunciation validation of non-native speakers: **large** is recommended if RAM ≥ 4 GB.

## Development

- **Python 3.11** required (type syntax `X | None`, `list[str]` + PyTorch/ML lib compatibility)
- **Environment**: Miniconda — `conda activate pronun`
- **Run**: `uvicorn main:app --reload --host 0.0.0.0 --port 8000` or `python main.py`
- **Production**: `uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1 --log-level warning --proxy-headers`
- **Tests**: `pytest tests/ -v` — 318 tests, async tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- **Formatting**: Black (line-length=100), Ruff for linting (`E`, `F`, `I`, `W` rules)
- **Logging**: Use `from loguru import logger` everywhere, never `print()` or stdlib `logging`

## Code Conventions

- All modules start with `from __future__ import annotations`
- Use type hints everywhere; prefer `X | None` over `Optional[X]`
- Pydantic models use `Field(...)` with descriptions for API docs
- API routes go in `app/api/routes/` and are registered in `app/application.py`
- Audio is always processed as 16kHz mono float32 numpy arrays
- GOP scores are normalised from raw log-probs (empirical range −25…−3) to 0–100 scale
- Never commit real `API_KEY` values — use `.env.example` for documentation
