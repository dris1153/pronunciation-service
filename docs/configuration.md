<!-- doc-id: docs-configuration | rev: 4502e42a -->
# Configuration

All settings are environment variables (or entries in `.env`, resolved from the project root). Names are case-insensitive. The template is [`.env.example`](../.env.example); the source of truth is [`app/core/config.py`](../app/core/config.py).

> `.env` accepts only the names below. An unknown key (a typo, or build-only values such as `V2_MODEL_REPO`) makes startup fail with `extra_forbidden`. Put build-only values in the build environment, not in `.env`.

## Application

| Variable | Default | Description |
| --- | --- | --- |
| `APP_NAME` | `Pronunciation Validator` | Shown in OpenAPI and `model-info` |
| `APP_VERSION` | `1.0.0` | Shown in OpenAPI, `/health`, `model-info` |
| `APP_HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Server port (Railway injects it at runtime) |
| `DEBUG` | `false` | `true` skips API-key strength validation and uses human-readable logs. Always `false` in production |
| `LOG_LEVEL` | `INFO` | Log level. `DEBUG=false` logs one JSON line per record |

## v1 models (Wav2Vec2)

| Variable | Default | Description |
| --- | --- | --- |
| `ASR_MODEL_NAME` | `facebook/wav2vec2-base-960h` | Hugging Face model id. `...-large-960h-lv60-self` is more accurate on accents but ~1.2 GB and ~7 s per clip |
| `ASR_MODEL_CACHE_DIR` | `./model_cache` | Model cache |
| `DEVICE` | `cpu` | `cpu` or `cuda` |
| `INFERENCE_BACKEND` | `torch_fp32` | `torch_fp32` or `torch_int8` (dynamic INT8 for the v1 ASR) |

## v2 phone model

| Variable | Default | Description |
| --- | --- | --- |
| `PHONE_MODEL_DIR` | `./data/models/hubert-phone-ctc` | Directory with `model.int8.onnx` (and optionally `model.onnx`), `vocab.json`, `scorer.json` |
| `PHONE_MODEL_INT8` | `true` | `true` loads `model.int8.onnx` (~116 MB, ~3x faster); `false` loads `model.onnx` (FP32, ~360 MB) |

Missing or unreadable files make `/api/v2/evaluate` answer `503`; v1 is unaffected. How the files get into an image: [deployment.md](deployment.md).

## Audio

| Variable | Default | Description |
| --- | --- | --- |
| `AUDIO_SAMPLE_RATE` | `16000` | Model sample rate (Hz). Both pipelines assume 16 kHz |
| `AUDIO_MAX_DURATION_SEC` | `30` | Longer audio is rejected with `400` |

The upload size limit (10 MB) and the accepted MIME types are constants in `app/core/constants.py`.

## Security

| Variable | Default | Description |
| --- | --- | --- |
| `API_KEY` | _(empty)_ | `X-API-Key` for protected endpoints. Required when `DEBUG=false`: at least 32 characters and not on the weak-key list. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SERVICE_API_KEY` | _(empty)_ | Enables per-end-user rate limiting for a trusted backend (`X-Service-Auth`). See [internal-integration.md](internal-integration.md) |
| `TRUSTED_PROXY_CIDRS_STR` | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | Peers whose `X-Forwarded-For` is trusted. Narrow it to your proxy |
| `CORS_ORIGINS_STR` | `*` | Comma-separated origins (or a JSON array). `*` is for development only |

## Rate limiting, timeouts, concurrency

| Variable | Default | Description |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | Master switch (turn off in tests and CI) |
| `RATE_LIMIT_EVALUATE_PER_MINUTE` | `20` | Limit for each of `/api/v1/evaluate` and `/api/v2/evaluate` (each route keeps its own counter) |
| `RATE_LIMIT_TRANSCRIBE_PER_MINUTE` | `15` | |
| `RATE_LIMIT_TEXT_ANALYSIS_PER_MINUTE` | `120` | |
| `REQUEST_TIMEOUT_SEC` | `90` | Longer requests return `504` |
| `MAX_CONCURRENT_INFERENCES` | `0` | Inference slots. `0` = auto (cores - 1, capped at 4). Threads per slot = cores / slots. Measured: 4 vCPU -> `2`; 2 vCPU -> auto (1 slot) |
| `INFERENCE_QUEUE_TIMEOUT_SEC` | `60` | Time a request may wait for a slot before `503` with `Retry-After` |

Under Docker `--cpus` or Railway the CPU quota is invisible to the affinity probe; set `OMP_NUM_THREADS` to the vCPU count and it wins over the computed value.

## Prosody (v1 only)

| Variable | Default | Description |
| --- | --- | --- |
| `PROSODY_PITCH_MIN_HZ` / `PROSODY_PITCH_MAX_HZ` | `65` / `600` | pyin search range |
| `PROSODY_MONOTONE_THRESHOLD` | `0.08` | Pitch coefficient of variation below this is monotone |
| `PROSODY_PITCH_CV_UPPER` | `0.25` | CV at or above this scores 100. Must be greater than the monotone threshold |

## Build-time only (not read from `.env`)

| Name | Where | Description |
| --- | --- | --- |
| `V2_MODEL_REPO` | Docker build arg / nixpacks build variable | Private Hugging Face repo with the v2 files, for example `dris1153/pronunciation-v2` |
| `HF_TOKEN` | Docker build secret (`--secret id=HF_TOKEN,env=HF_TOKEN`) / nixpacks build variable | Read token for that repo. Never commit it or bake it into an image layer |
| `ASR_MODEL_NAME` | Docker build arg | Overrides the v1 model baked into the image |
