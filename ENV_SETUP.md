# Environment variables

Every variable the service reads, when it is read, and what to set on Coolify (Dockerfile build pack).

**Stage legend**

| Stage | Meaning | Coolify checkbox |
| --- | --- | --- |
| **Build** | Read only while the image is built (`download_model.py`). Not needed in the running container. | Available at Buildtime **on**, Runtime **off** |
| **Runtime** | Read by the app (`app/core/config.py`) when the container starts. | Available at Runtime **on**, Buildtime off |
| **Both** | Needed at build and at start, and the two values must match. | Both on |

Names are case-insensitive. Unset variables fall back to the default shown.

## 1. Required in production

| Variable | Stage | Example / default | Notes |
| --- | --- | --- | --- |
| `API_KEY` | Runtime | 32+ random chars | Required when `DEBUG=false`; the app refuses to start on a weak or short key. Generate: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `DEBUG` | Runtime | `false` | `true` skips API key validation and switches logs to colour text. Never `true` in production |
| `CORS_ORIGINS_STR` | Runtime | `https://app.example.com` | Comma-separated origins (or a JSON array). Default `*` allows everyone |

## 2. v2 model download (build only)

| Variable | Stage | Example / default | Notes |
| --- | --- | --- | --- |
| `V2_MODEL_REPO` | **Build** | `dris1153/pronunciation-v2` | Public HF repo with `model.int8.onnx`, `vocab.json`, `scorer.json`. Unset = v2 step skipped and `/api/v2/evaluate` answers 503. Not a `Settings` field: keep it out of runtime and out of `.env` |
| `HF_TOKEN` | **Build** (secret) | `hf_xxx` (read-only) | Optional: only needed for a private `V2_MODEL_REPO`. Read by `download_model.py` only. In Coolify set Build secrets to *Docker BuildKit secrets*. The app never reads it, so leave Runtime off. Never commit it |

The upload side uses a separate **write** token on your own machine: `HF_TOKEN=<write> python scripts/upload_v2_model.py --repo <org>/<repo>`.

## 3. Models and inference

| Variable | Stage | Default | Notes |
| --- | --- | --- | --- |
| `ASR_MODEL_NAME` | Both | `facebook/wav2vec2-base-960h` | v1 model. Baked into the image at build (Dockerfile `ARG`). If the runtime value differs from the baked one, the container downloads the model at start and uses more RAM. Easiest: do not set it |
| `ASR_MODEL_CACHE_DIR` | Runtime | `./model_cache` | Resolves to `/app/model_cache`, where the Dockerfile bakes v1. Do not change |
| `PHONE_MODEL_DIR` | Runtime | `./data/models/hubert-phone-ctc` | Where v2 files are loaded from. Do not change unless you move them |
| `PHONE_MODEL_INT8` | Runtime | `true` | `true` loads `model.int8.onnx` (~116 MB, faster). `false` loads FP32 `model.onnx` (~360 MB), which the image does not ship |
| `DEVICE` | Runtime | `cpu` | `cpu` or `cuda`. The image is CPU-only |
| `INFERENCE_BACKEND` | Runtime | `torch_fp32` | v1 only: `torch_fp32` or `torch_int8` |

## 4. Server, limits and concurrency

| Variable | Stage | Default | Notes |
| --- | --- | --- | --- |
| `PORT` | Runtime | `8001` (Dockerfile) | Must equal Coolify *Ports Exposes*. Leave unset |
| `APP_HOST` | Runtime | `0.0.0.0` | Leave as is |
| `APP_NAME`, `APP_VERSION` | Runtime | `Pronunciation Validator`, `1.0.0` | Cosmetic |
| `AUDIO_SAMPLE_RATE` | Runtime | `16000` | Leave as is; models expect 16 kHz |
| `AUDIO_MAX_DURATION_SEC` | Runtime | `30` | Longer audio is rejected |
| `REQUEST_TIMEOUT_SEC` | Runtime | `90` | Slower requests return 504 |
| `MAX_CONCURRENT_INFERENCES` | Runtime | `0` (auto) | Auto picks 1 on 2 vCPU. Set 2 on 4 vCPU |
| `INFERENCE_QUEUE_TIMEOUT_SEC` | Runtime | `60` | Waiting longer returns 503. Set Coolify graceful shutdown above this plus one inference |
| `OMP_NUM_THREADS` | Runtime | unset | Set to the container CPU limit when you cap CPUs, so ONNX/torch do not oversubscribe |

## 5. Security and rate limiting

| Variable | Stage | Default | Notes |
| --- | --- | --- | --- |
| `RATE_LIMIT_ENABLED` | Runtime | `true` | Master switch. Keep `true` in production |
| `RATE_LIMIT_EVALUATE_PER_MINUTE` | Runtime | `20` | Per key (IP, or end user via service auth) |
| `RATE_LIMIT_TRANSCRIBE_PER_MINUTE` | Runtime | `15` | |
| `RATE_LIMIT_TEXT_ANALYSIS_PER_MINUTE` | Runtime | `120` | |
| `TRUSTED_PROXY_CIDRS_STR` | Runtime | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | Peers whose `X-Forwarded-For` is trusted. Default fits Coolify's Traefik; narrow it with `docker network inspect coolify` |
| `SERVICE_API_KEY` | Runtime | empty (off) | Set when a trusted backend calls this service and wants per-end-user limits (`X-Service-Auth` + `X-End-User-Id`). 48+ random chars |

## 6. Prosody (v1 only)

| Variable | Stage | Default | Notes |
| --- | --- | --- | --- |
| `PROSODY_PITCH_MIN_HZ` | Runtime | `65.0` | pyin lower bound |
| `PROSODY_PITCH_MAX_HZ` | Runtime | `600.0` | pyin upper bound |
| `PROSODY_MONOTONE_THRESHOLD` | Runtime | `0.08` | Pitch CV below this counts as monotone |
| `PROSODY_PITCH_CV_UPPER` | Runtime | `0.25` | Must be greater than the monotone threshold or startup fails |

## 7. Logging

| Variable | Stage | Default | Notes |
| --- | --- | --- | --- |
| `LOG_LEVEL` | Runtime | `INFO` | JSON lines when `DEBUG=false` |

## 8. Set by the Dockerfile (do not override)

| Variable | Stage | Value | Purpose |
| --- | --- | --- | --- |
| `TRANSFORMERS_CACHE` | Both | `/app/model_cache` | Hugging Face cache used by the baked v1 model |
| `TMPDIR` | Runtime | `/app/tmp` | Writable temp dir for the non-root user |
| `V2_MODEL_REPO` | Build | from build arg | The Dockerfile copies the build arg into `ENV`; it is not a secret |

## Minimal Coolify setup

| Name | Runtime | Buildtime |
| --- | --- | --- |
| `API_KEY` | on | off |
| `DEBUG` = `false` | on | off |
| `CORS_ORIGINS_STR` | on | off |
| `V2_MODEL_REPO` | off | on |
| `HF_TOKEN` (private model repo only) | off | on (build secret) |

Everything else can stay at its default. Other docs: [docs/configuration.md](docs/configuration.md), [docs/deployment.md](docs/deployment.md).
