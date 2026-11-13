<!-- doc-id: docs-architecture | lang: es | source-rev: f54d8e3a -->

> 🌐 **Traducción al español** de [`docs/architecture.md`](../../../docs/architecture.md) (rev `f54d8e3a`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Arquitectura

## Visión general del sistema

```mermaid
flowchart LR
    client["Cliente / backend del producto"] -->|"audio + reference_text<br/>X-API-Key"| mw
    subgraph svc["Servicio FastAPI (un proceso, un worker)"]
        mw["Middleware<br/>CORS, límite de peticiones, timeout, request id"] --> val["Autenticación + validación de la subida<br/>app/api/upload.py"]
        val --> sem["Semáforo de inferencia<br/>cola, 503 si está llena"]
        sem --> v1["Pipeline v1<br/>ASR Wav2Vec2, g2p, GOP, pyin"]
        sem --> v2["Pipeline v2<br/>phone CTC en ONNX, características GOP, evaluador aprendido"]
        mw --> misc["text-analysis, transcribe,<br/>model-info, health"]
    end
    v1 --> w1[("Pesos de Wav2Vec2<br/>incluidos en la imagen")]
    v2 --> w2[("model.int8.onnx, vocab.json, scorer.json<br/>desde el repo HF privado en el build")]
```

Todo se ejecuta en un solo proceso porque los modelos son grandes y se cargan una única vez; cada worker adicional de uvicorn cargaría su propia copia. La inferencia en CPU está limitada por un semáforo (`MAX_CONCURRENT_INFERENCES`), y el trabajo bloqueante se ejecuta en un hilo de trabajo para que el bucle de eventos quede libre.

## v1 y v2 lado a lado

```mermaid
flowchart TB
    subgraph V1["v1 (/api/v1/evaluate)"]
        direction TB
        a1["Audio"] --> b1["ASR Wav2Vec2<br/>letras A-Z"]
        b1 --> c1["Transcripción"]
        c1 --> d1["g2p a IPA, alineación de texto<br/>precisión IPA"]
        b1 --> e1["Alineación forzada CTC sobre las probabilidades a posteriori de las letras<br/>GOP"]
        a1 --> f1["Tono con pyin<br/>prosodia"]
        d1 --> g1["Fórmulas ajustadas a mano<br/>subpuntuaciones al estilo Azure"]
        e1 --> g1
        f1 --> g1
    end
    subgraph V2["v2 (/api/v2/evaluate)"]
        direction TB
        a2["Audio"] --> b2["HuBERT phone CTC<br/>41 fonemas IPA"]
        t2["Texto de referencia"] --> c2["g2p a fonemas esperados"]
        b2 --> d2["Alineación forzada de los<br/>fonemas esperados"]
        c2 --> d2
        d2 --> e2["Características GOP + fonemas oídos"]
        e2 --> f2["Evaluador aprendido<br/>entrenado con puntuaciones de expertos"]
    end
```

| | v1 | v2 |
| --- | --- | --- |
| Unidad puntuada | palabras reconocidas por el ASR | cada fonema esperado |
| Evidencia de fonemas | probabilidades a posteriori de letras | probabilidades a posteriori de fonemas |
| Puntuaciones | fórmulas (55% IPA + 45% GOP, global con mínimo ordenado) | aprendidas de las puntuaciones de expertos de speechocean762 |
| Prosodia / fluidez | tono con pyin, velocidad del habla, pausas | aprendidas de las características de alineación (sin detector de tono) |
| Runtime | PyTorch | ONNX Runtime (INT8), sin PyTorch en el código de v2 |
| Latencia p50 (clip de 3.4 s, 4 vCPU) | 381 ms | 125 ms |

## Una petición v2

```mermaid
sequenceDiagram
    participant C as Cliente
    participant R as Ruta /api/v2/evaluate
    participant Q as Semáforo de inferencia
    participant S as Servicio V2 (hilo de trabajo)
    participant O as Modelo de fonemas ONNX
    participant Sc as Evaluador
    C->>R: audio, reference_text, X-API-Key
    R->>R: límite de peticiones, API key, validar texto, tamaño, MIME, duración
    alt entrada no válida
        R-->>C: 400 / 401 / 403 / 422 / 429
    end
    R->>R: obtener el servicio V2
    alt archivos del modelo ausentes o corruptos
        R-->>C: 503
    end
    R->>Q: esperar un hueco (hasta 60 s)
    alt timeout de la cola
        Q-->>C: 503 Retry-After
    end
    Q->>S: ejecutar en un hilo
    S->>S: decodificar audio, comprobar silencio
    S->>O: forma de onda
    O-->>S: log-posteriors
    S->>S: alinear fonemas esperados, características GOP, fonemas oídos
    alt silencio, o se oye menos del 20% de los fonemas esperados
        S-->>C: 200 respuesta de puntuación cero
    else se encuentra habla
        S->>Sc: características por fonema
        Sc-->>S: puntuaciones de fonema, palabra y enunciado
        S-->>C: 200 respuesta con start_ms / end_ms por palabra
    end
```

Los errores de valor del servicio (audio demasiado corto, referencia sin ninguna palabra pronunciable) se convierten en `400`; cualquier error inesperado se convierte en `500` con un mensaje genérico.

## Arranque

```mermaid
flowchart TD
    s0["inicio de lifespan"] --> s1["Comprobar que TMPDIR y los directorios de caché son escribibles"]
    s1 --> s2["Fijar los hilos de torch (salvo si hay OMP_NUM_THREADS)"]
    s2 --> s3["Advertir si API_KEY está vacía"]
    s3 --> s4["Precargar v1: ASR, IPA, GOP, prosodia"]
    s4 --> s5{"Precargar v2"}
    s5 -->|ok| s6["Comprobar ffmpeg"]
    s5 -->|"cualquier error"| s5w["Registrar advertencia, /api/v2 responde 503"] --> s6
    s6 --> s7["Servir"]
```

Un modelo v1 defectuoso detiene el arranque; un modelo v2 defectuoso o ausente nunca lo hace.

## Organización del código

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

Detalles por archivo: [structure.md](structure.md). El flujo de una petición v1 en forma de texto: [workflow.md](workflow.md).
