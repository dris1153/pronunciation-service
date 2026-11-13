# API Reference

Interactive docs: `GET /docs` (Swagger UI) and `GET /redoc`. This page is the written reference.

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `GET /health` | no | Liveness and model-loaded flag |
| `GET /docs` | no | Swagger UI |
| `GET /api/v1/model-info` | no | Service metadata and limits |
| `POST /api/v1/evaluate` | yes | Pronunciation score, v1 pipeline (Wav2Vec2 ASR) |
| `POST /api/v2/evaluate` | yes | Pronunciation score, v2 pipeline (phone CTC + learned scorer) |
| `GET /api/v1/text-analysis` | yes | Text to IPA with per-word phonemes |
| `POST /api/v1/transcribe` | yes | Audio to text (v1 ASR), no scoring |

## Authentication

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

Per-end-user quotas, `X-Service-Auth` / `X-End-User-Id` headers and backend wrappers: see [internal-integration.md](internal-integration.md).

## Endpoints

### `GET /health`

Health check — returns service status and model load state. **No authentication required.**

### `POST /api/v1/evaluate`

Evaluate pronunciation quality. **Requires `X-API-Key` header.**

**Request** (multipart/form-data):

| Field            | Type   | Description                            |
| ---------------- | ------ | -------------------------------------- |
| `audio`          | File   | Audio file (wav, mp3, ogg, flac, webm) |
| `reference_text` | string | Text the speaker should have said      |

> **Upload limit:** Maximum audio file size is **10 MB**. Larger files return HTTP 400.

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


### `POST /api/v2/evaluate`

Same request (multipart: `audio`, `reference_text`), same auth, rate limit, upload limits and error codes as v1. The response has the **v1 shape plus word timing**; scores come from a phoneme-level model and a learned scorer. v1 is unchanged.

| Field | v2 behaviour |
| --- | --- |
| `results.word_details[].start_ms` / `end_ms` | **New.** Word position in the audio (ms). |
| `transcribed_text` | The heard **IPA string**, not words (there is no word ASR). |
| `phoneme_details[].actual_ipa` | The phone the model heard (empty = not heard). |
| `phoneme_details[].is_correct_ipa` | Learned verdict (phone score < 1.48 of 2), **not** `actual_ipa == expected_ipa`. On speechocean762 test, 18% of phones are heard differently yet accepted (accent-neutral variants such as ɪ/i, ʌ/ɑ) and 0.3% are heard correctly yet flagged. Use it for "needs practice"; use `actual_ipa` for "what it sounded like". |
| `phoneme_details[].gop_score` | Phone score on 0-100 (learned score x 50). |
| `overall_score`, `accuracy_score`, `fluency_score`, `prosody_score` | Learned predictions mapped through one stricter curve, `100 x (s/10)^1.4`. Not comparable with v1 numbers. |
| `completeness_score` | Share of expected phones that were heard (rule, not learned). |
| `error_type` | `Omission` (no phone of the word heard), `Mispronunciation` (word score < 60), then `UnexpectedBreak` / `MissingBreak` from the aligned word gaps, as in v1. `Insertion` is never set on words (same as v1). |

Behaviour worth knowing:

- Audio with no decodable speech (silence, noise, a different sentence; fewer than 20% of the expected phones heard) returns the zero-score response instead of a guess.
- Words that contain no pronounceable phone (for example a lone `'`) are left out of `word_details`; a reference with no pronounceable word returns `400`.
- Audio shorter than 25 ms, or too short to align the reference text, returns `400`.
- If the v2 model files are not on the server the endpoint returns `503` and v1 keeps working.

Details of the model and scoring: [scoring-v2.md](scoring-v2.md). Moving a client from v1: [internal-integration.md](internal-integration.md#10-switching-a-client-to-apiv2evaluate).

<details>
<summary>Example response (real output for the sanity clip "yellow word" scored against "hello world")</summary>

```json
{
  "reference_text": "hello world",
  "transcribed_text": "jɛloʊ wɝd",
  "results": {
    "reference_ipa": "həloʊ wɝld",
    "actual_ipa": "jɛloʊ wɝd",
    "word_details": [
      {
        "word": "hello",
        "expected_ipa": "həloʊ",
        "actual_ipa": "jɛloʊ",
        "phoneme_details": [
          {
            "expected_ipa": "h",
            "actual_ipa": "j",
            "is_correct_ipa": false,
            "confidence_ipa": 0.0,
            "gop_score": 67.56,
            "gop_quality": "good"
          },
          {
            "expected_ipa": "ə",
            "actual_ipa": "ɛ",
            "is_correct_ipa": false,
            "confidence_ipa": 0.0,
            "gop_score": 25.03,
            "gop_quality": "poor"
          },
          {
            "expected_ipa": "l",
            "actual_ipa": "l",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 93.64,
            "gop_quality": "excellent"
          },
          {
            "expected_ipa": "oʊ",
            "actual_ipa": "oʊ",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 96.7,
            "gop_quality": "excellent"
          }
        ],
        "ipa_accuracy": 50.0,
        "word_gop_score": 58.92,
        "word_gop_quality": "fair",
        "error_type": "Mispronunciation",
        "start_ms": 160,
        "end_ms": 440
      },
      {
        "word": "world",
        "expected_ipa": "wɝld",
        "actual_ipa": "wɝd",
        "phoneme_details": [
          {
            "expected_ipa": "w",
            "actual_ipa": "w",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 97.82,
            "gop_quality": "excellent"
          },
          {
            "expected_ipa": "ɝ",
            "actual_ipa": "ɝ",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 95.1,
            "gop_quality": "excellent"
          },
          {
            "expected_ipa": "l",
            "actual_ipa": "",
            "is_correct_ipa": true,
            "confidence_ipa": 0.0,
            "gop_score": 85.5,
            "gop_quality": "excellent"
          },
          {
            "expected_ipa": "d",
            "actual_ipa": "d",
            "is_correct_ipa": true,
            "confidence_ipa": 1.0,
            "gop_score": 91.06,
            "gop_quality": "excellent"
          }
        ],
        "ipa_accuracy": 100.0,
        "word_gop_score": 91.64,
        "word_gop_quality": "excellent",
        "error_type": "None",
        "start_ms": 560,
        "end_ms": 920
      }
    ],
    "overall_ipa_accuracy": 75.0,
    "overall_gop_score": 81.55,
    "overall_gop_quality": "excellent"
  },
  "accuracy_score": 57.26,
  "completeness_score": 87.5,
  "fluency_score": 74.69,
  "prosody_score": 68.98,
  "overall_score": 55.8,
  "level": "fair",
  "feedback": "Fair pronunciation. Several sounds need practice. Focus on the phonemes marked with low scores. Score: 55.8/100."
}
```

</details>

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

> **Upload limit:** Maximum audio file size is **10 MB**. Larger files return HTTP 400.

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
  "max_upload_mb": 10,
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

## Errors

| Status | When |
| --- | --- |
| `400` | Empty or oversized upload (> 10 MB), unsupported format, audio too long (> 30 s) or too short, empty reference text, v2: reference without pronounceable words |
| `401` / `403` | Missing / wrong `X-API-Key` |
| `422` | Reference text rejected by validation |
| `429` | Rate limit exceeded (per IP, or per end user in [internal mode](internal-integration.md)) |
| `503` | Inference queue full (`Retry-After`), or v2 model files not available |
| `504` | Request timeout (`REQUEST_TIMEOUT_SEC`) |
| `500` | Unexpected error |

## Example cURL

```bash
# Evaluate pronunciation, v1 (requires API key)
curl -X POST http://localhost:8000/api/v1/evaluate \
  -H "X-API-Key: your-secret-api-key-here" \
  -F "audio=@recording.wav" \
  -F "reference_text=hello world"

# Evaluate pronunciation, v2 (same request, response adds word timing)
curl -X POST http://localhost:8000/api/v2/evaluate \
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
