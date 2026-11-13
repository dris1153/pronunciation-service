<!-- doc-id: docs-workflow | lang: es | source-rev: b030953c -->

> 🌐 **Traducción al español** de [`docs/workflow.md`](../../../docs/workflow.md) (rev `b030953c`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Flujo de trabajo y de las peticiones

> Pronunciation Validation Service — cómo fluyen las peticiones, cómo funciona la autenticación y cómo se configura el despliegue.
> Las secciones 1-2 describen el pipeline **v1**; los diagramas de v1 frente a v2, la secuencia de una petición v2 y el arranque están en [architecture.md](architecture.md).

---

## 1. Visión general de la arquitectura

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

## 2. Flujo de una petición (POST /api/v1/evaluate)

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

### Paso a paso

| #   | Paso                     | Componente             | Descripción                                                                                                                                                         |
| --- | ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Autenticación**        | `dependencies.py`      | Valida la cabecera `X-API-Key` (se omite si `API_KEY` está vacía)                                                                                                   |
| 2   | **Validación de la entrada** | `pronunciation.py` | Comprueba el tipo de contenido del audio, el tamaño del archivo (≤10 MB) y que el texto de referencia no esté vacío                                                 |
| 3   | **Carga del audio**      | `utils/audio.py`       | Decodifica los bytes de audio → array numpy float32 mono de 16 kHz (librosa)                                                                                        |
| 4   | **Transcripción**        | `ASRService`           | El modelo Wav2Vec2 produce texto a partir del habla                                                                                                                 |
| 5   | **Filtrado de muletillas** | `utils/text.py`      | Elimina las palabras de disfluencia (uh, um, hmm…) mediante `filter_fillers(text_to_words(...))`                                                                    |
| 6   | **Conversión a IPA**     | `IPAService`           | Tanto el texto de referencia como la transcripción → secuencias de fonemas IPA                                                                                      |
| 7   | **Comparación IPA**      | `PronunciationService` | Alinea y compara los fonemas esperados con los reales, y calcula la precisión                                                                                       |
| 8   | **Puntuación GOP**       | `GOPService`           | Comprobación de silencio → log-posteriors CTC → alineación forzada → GOP por fonema + tiempos                                                                       |
| 9   | **Análisis de prosodia** | `ProsodyService`       | Extracción del tono (pyin) → puntuación de varianza, rango y contorno → detección de monotonía                                                                      |
| 10  | **Clasificación de errores** | `PronunciationService` | Tipo de error por palabra: None / Mispronunciation / Omission / Insertion / UnexpectedBreak / MissingBreak                                                      |
| 11  | **Subpuntuaciones**      | `PronunciationService` | `accuracy_score` = 55% IPA + 45% GOP; `completeness_score` = razón ponderada por la precisión; `fluency_score` = velocidad + pausas; `prosody_score` = entonación + velocidad + ritmo |
| 12  | **Puntuación final**     | `PronunciationService` | Global = 0.4×s0 + 0.2×s1 + 0.2×s2 + 0.2×s3 (4 subpuntuaciones ordenadas de menor a mayor)                                                                           |
| 13  | **Respuesta**            | `pronunciation.py`     | Devuelve el JSON `PronunciationResponse` con el nivel y la retroalimentación                                                                                        |

---

### Flujo de una petición v2 (POST /api/v2/evaluate)

Misma validación, autenticación, límite de peticiones y semáforo de inferencia que v1 (`app/api/upload.py`) y, después, sin torch de por medio:
decodificación del audio → phone CTC en ONNX (fotogramas de 20 ms) → alineación forzada CTC en numpy → características GOP por fonema + fonemas oídos → evaluador aprendido
(MLP por fonema → ridge de palabra/enunciado) → respuesta con la forma de v1 y tiempos por palabra. Los errores de pausa reutilizan las reglas de pausa de v1 sobre los intervalos de palabras alineadas.

## 3. Flujo de autenticación

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

| Endpoint                    | Auth requerida                       |
| --------------------------- | ------------------------------------ |
| `GET /health`               | ❌ No — público para comprobaciones de estado |
| `GET /docs`                 | ❌ No — Swagger UI                   |
| `GET /redoc`                | ❌ No — ReDoc UI                     |
| `GET /api/v1/model-info`    | ❌ No — metadatos públicos del servicio |
| `POST /api/v1/evaluate`     | ✅ Sí — requiere la cabecera `X-API-Key` |
| `GET /api/v1/text-analysis` | ✅ Sí — requiere la cabecera `X-API-Key` |
| `POST /api/v1/transcribe`   | ✅ Sí — requiere la cabecera `X-API-Key` |

---

## 4. Arranque de la aplicación (Lifespan)

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

## 5. Flujos de despliegue

### 5a. Railway (producción)

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

**Puntos clave:**

- Railway inyecta `PORT` en tiempo de ejecución — pydantic-settings lo lee de forma nativa (sin expansión de `$PORT` en el shell)
- El modelo se **incluye** en la imagen de Docker durante el build (Railway no tiene volúmenes persistentes)
- `ENV ASR_MODEL_NAME` se define **antes** del paso `RUN` de descarga del modelo para que funcionen las sustituciones con `--build-arg`
- Las variables de entorno (`API_KEY`, `ASR_MODEL_NAME`, etc.) se definen en el panel de Railway
- `railway.toml` tiene `healthcheckPath = "/health"` y `healthcheckTimeout = 120`
- Sin `startCommand` — se usa directamente el CMD del Dockerfile

---

## 6. Sistema de puntuación

Las fórmulas de v1 (precisión, completitud, fluidez, prosodia, global, tipos de error) están en [scoring-v1.md](scoring-v1.md); la puntuación nativa de fonemas de v2 está en [scoring-v2.md](scoring-v2.md).

---

## 7. Formatos de audio admitidos

| Formato | Tipos MIME                              |
| ------ | ---------------------------------------- |
| WAV    | `audio/wav`, `audio/x-wav`, `audio/wave` |
| MP3    | `audio/mpeg`, `audio/mp3`                |
| OGG    | `audio/ogg`                              |
| FLAC   | `audio/flac`                             |
| WebM   | `audio/webm`                             |

Todo el audio se convierte a arrays numpy **float32 mono de 16 kHz** mediante librosa.

---

## 8. Esquema de respuesta de la API

Esquemas de respuesta y ejemplos de cada endpoint, v1 y v2: [api.md](api.md).

---

## 9. Benchmarks de recursos

Latencia y memoria medidas para v1, v2 FP32 y v2 INT8: [evaluation.md](evaluation.md). Dimensionamiento y reglas de ejecución: [deployment.md](deployment.md).
