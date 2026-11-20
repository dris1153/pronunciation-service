<!-- doc-id: docs-architecture | rev: ec588fa9 -->
# Architecture

## System overview

```mermaid
flowchart LR
    client["Client / product backend"] -->|"audio + reference_text<br/>X-API-Key"| mw
    subgraph svc["FastAPI service (one process, one worker)"]
        mw["Middleware<br/>CORS, rate limit, timeout, request id"] --> val["Auth + upload validation<br/>app/api/upload.py"]
        val --> sem["Inference semaphore<br/>queue, 503 when full"]
        sem --> v1["v1 pipeline<br/>Wav2Vec2 ASR, g2p, GOP, pyin"]
        sem --> v2["v2 pipeline<br/>ONNX phone CTC, GOP features, learned scorer"]
        mw --> misc["text-analysis, transcribe,<br/>model-info, health"]
    end
    v1 --> w1[("Wav2Vec2 weights<br/>baked into the image")]
    v2 --> w2[("model.int8.onnx, vocab.json, scorer.json<br/>from the HF repo at build time")]
```

Everything runs in one process because the models are large and loaded once; extra uvicorn workers would each load their own copy. CPU inference is bounded by a semaphore (`MAX_CONCURRENT_INFERENCES`), and the blocking work runs in a worker thread so the event loop stays free.

## v1 and v2 side by side

```mermaid
flowchart TB
    subgraph V1["v1 (/api/v1/evaluate)"]
        direction TB
        a1["Audio"] --> b1["Wav2Vec2 ASR<br/>letters A-Z"]
        b1 --> c1["Transcript"]
        c1 --> d1["g2p to IPA, text alignment<br/>IPA accuracy"]
        b1 --> e1["CTC forced alignment on letter posteriors<br/>GOP"]
        a1 --> f1["pyin pitch<br/>prosody"]
        d1 --> g1["Hand-tuned formulas<br/>Azure-style sub-scores"]
        e1 --> g1
        f1 --> g1
    end
    subgraph V2["v2 (/api/v2/evaluate)"]
        direction TB
        a2["Audio"] --> b2["HuBERT phone CTC<br/>41 IPA phones"]
        t2["Reference text"] --> c2["g2p to expected phones"]
        b2 --> d2["Forced alignment of the<br/>expected phones"]
        c2 --> d2
        d2 --> e2["GOP features + heard phones"]
        e2 --> f2["Learned scorer<br/>trained on expert scores"]
    end
```

| | v1 | v2 |
| --- | --- | --- |
| Unit scored | words recognised by ASR | each expected phone |
| Phone evidence | letter posteriors | phone posteriors |
| Scores | formulas (55% IPA + 45% GOP, sorted-min overall) | learned from speechocean762 expert scores |
| Prosody / fluency | pyin pitch, speech rate, pauses | learned from alignment features (no pitch tracker) |
| Runtime | PyTorch | ONNX Runtime (INT8), no PyTorch in the v2 code |
| Latency p50 (3.4 s clip, 4 vCPU) | 381 ms | 125 ms |

## One v2 request

```mermaid
sequenceDiagram
    participant C as Client
    participant R as Route /api/v2/evaluate
    participant Q as Inference semaphore
    participant S as V2 service (worker thread)
    participant O as ONNX phone model
    participant Sc as Scorer
    C->>R: audio, reference_text, X-API-Key
    R->>R: rate limit, API key, validate text, size, MIME, duration
    alt invalid input
        R-->>C: 400 / 401 / 403 / 422 / 429
    end
    R->>R: get V2 service
    alt model files missing or corrupt
        R-->>C: 503
    end
    R->>Q: wait for a slot (up to 60 s)
    alt queue timeout
        Q-->>C: 503 Retry-After
    end
    Q->>S: run in thread
    S->>S: decode audio, silence check
    S->>O: waveform
    O-->>S: log-posteriors
    S->>S: align expected phones, GOP features, heard phones
    alt silent, or under 20% of expected phones heard
        S-->>C: 200 zero-score response
    else speech found
        S->>Sc: per-phone features
        Sc-->>S: phone, word, utterance scores
        S-->>C: 200 response with word start_ms / end_ms
    end
```

Value errors from the service (audio too short, reference with no pronounceable word) become `400`; anything unexpected becomes `500` with a generic message.

## Startup

```mermaid
flowchart TD
    s0["lifespan start"] --> s1["Check TMPDIR and cache dirs are writable"]
    s1 --> s2["Set torch threads (unless OMP_NUM_THREADS)"]
    s2 --> s3["Warn if API_KEY is empty"]
    s3 --> s4["Preload v1: ASR, IPA, GOP, prosody"]
    s4 --> s5{"Preload v2"}
    s5 -->|ok| s6["ffmpeg check"]
    s5 -->|"any error"| s5w["Log warning; /api/v2 answers 503"] --> s6
    s6 --> s7["Serve"]
```

A broken v1 model stops startup; a broken or missing v2 model never does.

## Code layout

```
app/
  application.py            FastAPI factory + lifespan (model preload)
  api/
    routes/                 health, ipa, model_info, pronunciation (v1), pronunciation_v2, transcribe
    dependencies.py         API key, service lookup (v1, v2 with 503)
    middleware.py           CORS, rate limit, timeout, exception handlers
    upload.py               upload + reference text validation shared by v1 and v2
  core/                     config (pydantic-settings), concurrency, constants, logging
  models/schemas.py         Pydantic schemas (v1 and additive V2 subclasses)
  services/
    pronunciation_service.py  v1 orchestrator
    asr_service.py, gop_service.py, ipa_service.py, prosody_service.py   v1 components
    phoneme_align.py        phone similarity groups + DP alignment (no torch, shared)
    scoring_rules.py        level/feedback, error types, break detection (no torch, shared)
    v2/
      phone_model.py        ONNX session -> log-posteriors
      ctc_align.py          numpy CTC forced alignment
      gop_features.py       GOP features, heard phones
      scorer.py             numpy phone MLP + word/utterance ridge
      analyser.py           audio + text -> V2Analysis
      pronunciation_v2_service.py   response assembly, gates, score curve
  utils/                    audio I/O, text normalisation
training/                   offline training and export (own CUDA venv, not imported by app/)
scripts/                    evaluation harness, sanity set, HF upload
debugs/                     benchmark and diagnostics
tests/                      pytest suite (+ synthetic sanity recordings)
```

Details per file: [structure.md](structure.md). The v1 request flow in text form: [workflow.md](workflow.md).
