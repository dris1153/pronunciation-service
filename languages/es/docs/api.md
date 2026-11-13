<!-- doc-id: docs-api | lang: es | source-rev: 78459878 -->

> 🌐 **Traducción al español** de [`docs/api.md`](../../../docs/api.md) (rev `78459878`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Referencia de la API

Documentación interactiva: `GET /docs` (Swagger UI) y `GET /redoc`. Esta página es la referencia escrita.

| Endpoint | Auth | Propósito |
| --- | --- | --- |
| `GET /health` | no | Disponibilidad (liveness) e indicador de modelo cargado |
| `GET /docs` | no | Swagger UI |
| `GET /api/v1/model-info` | no | Metadatos y límites del servicio |
| `POST /api/v1/evaluate` | sí | Puntuación de pronunciación, pipeline v1 (ASR Wav2Vec2) |
| `POST /api/v2/evaluate` | sí | Puntuación de pronunciación, pipeline v2 (phone CTC + evaluador aprendido) |
| `GET /api/v1/text-analysis` | sí | Texto a IPA con los fonemas de cada palabra |
| `POST /api/v1/transcribe` | sí | Audio a texto (ASR v1), sin puntuación |

## Autenticación

Los endpoints protegidos requieren una cabecera `X-API-Key`.

| Comportamiento     | Condición                                          |
| ------------------ | -------------------------------------------------- |
| Auth **desactivada** | La variable de entorno `API_KEY` está vacía (comodidad para desarrollo local) |
| `401 Unauthorized` | Falta la cabecera cuando `API_KEY` está definida   |
| `403 Forbidden`    | La cabecera está presente pero el valor no coincide |
| ✅ Continúa        | La cabecera coincide con `API_KEY`                 |

> **Nota:** Cuando `API_KEY` está vacía, se registra una advertencia **una sola vez al arrancar** (no en cada petición) para recordarte que la definas antes de desplegar.

```bash
# Generate a strong key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Cuotas por usuario final, cabeceras `X-Service-Auth` / `X-End-User-Id` y wrappers de backend: consulta [internal-integration.md](internal-integration.md).

## Endpoints

### `GET /health`

Comprobación de estado — devuelve el estado del servicio y si el modelo está cargado. **No requiere autenticación.**

### `POST /api/v1/evaluate`

Evalúa la calidad de la pronunciación. **Requiere la cabecera `X-API-Key`.**

**Petición** (multipart/form-data):

| Campo            | Tipo   | Descripción                            |
| ---------------- | ------ | -------------------------------------- |
| `audio`          | File   | Archivo de audio (wav, mp3, ogg, flac, webm) |
| `reference_text` | string | Texto que el hablante debía decir      |

> **Límite de subida:** El tamaño máximo del archivo de audio es de **10 MB**. Los archivos más grandes devuelven HTTP 400.

**Respuesta** (JSON):

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

Misma petición (multipart: `audio`, `reference_text`), misma autenticación, límite de peticiones, límites de subida y códigos de error que v1. La respuesta tiene la **forma de v1 más los tiempos por palabra**; las puntuaciones provienen de un modelo a nivel de fonema y de un evaluador aprendido. v1 no cambia.

| Campo | Comportamiento en v2 |
| --- | --- |
| `results.word_details[].start_ms` / `end_ms` | **Nuevo.** Posición de la palabra en el audio (ms). |
| `transcribed_text` | La **cadena IPA** oída, no palabras (no hay ASR de palabras). |
| `phoneme_details[].actual_ipa` | El fonema que oyó el modelo (vacío = no se oyó). |
| `phoneme_details[].is_correct_ipa` | Veredicto aprendido (puntuación del fonema < 1.48 de 2), **no** `actual_ipa == expected_ipa`. En la prueba de speechocean762, el 18% de los fonemas se oyen distintos pero se aceptan (variantes neutras en cuanto al acento, como ɪ/i, ʌ/ɑ) y el 0.3% se oyen correctos pero se marcan. Úsalo para "necesita práctica"; usa `actual_ipa` para "cómo sonó". |
| `phoneme_details[].gop_score` | Puntuación del fonema en 0-100 (puntuación aprendida x 50). |
| `overall_score`, `accuracy_score`, `fluency_score`, `prosody_score` | Predicciones aprendidas pasadas por una curva más estricta, `100 x (s/10)^1.4`. No son comparables con los números de v1. |
| `completeness_score` | Proporción de fonemas esperados que se oyeron (regla, no aprendida). |
| `error_type` | `Omission` (no se oyó ningún fonema de la palabra), `Mispronunciation` (puntuación de la palabra < 60), y después `UnexpectedBreak` / `MissingBreak` a partir de los huecos entre palabras alineadas, como en v1. `Insertion` nunca se asigna a palabras (igual que en v1). |

Comportamiento que conviene conocer:

- El audio sin habla decodificable (silencio, ruido, una frase distinta; se oye menos del 20% de los fonemas esperados) devuelve la respuesta de puntuación cero en lugar de una conjetura.
- Las palabras que no contienen ningún fonema pronunciable (por ejemplo, un `'` suelto) se omiten de `word_details`; una referencia sin ninguna palabra pronunciable devuelve `400`.
- El audio de menos de 25 ms, o demasiado corto para alinear el texto de referencia, devuelve `400`.
- Si los archivos del modelo v2 no están en el servidor, el endpoint devuelve `503` y v1 sigue funcionando.

Detalles del modelo y de la puntuación: [scoring-v2.md](scoring-v2.md). Migrar un cliente desde v1: [internal-integration.md](internal-integration.md#10-migrar-un-cliente-a-apiv2evaluate).

<details>
<summary>Respuesta de ejemplo (salida real del clip de sanidad "yellow word" puntuado frente a "hello world")</summary>

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

Analiza texto en inglés y lo convierte a IPA con el desglose de fonemas de cada palabra. **Requiere la cabecera `X-API-Key`.**

**Parámetros de consulta:**

| Parámetro | Tipo   | Descripción                        |
| ------ | ------ | ------------------------------------- |
| `text` | string | Texto en inglés a analizar (1–500 caracteres) |

**Respuesta** (JSON):

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

Sube audio y obtén la transcripción en texto plano (sin puntuación). **Requiere la cabecera `X-API-Key`.**

**Petición** (multipart/form-data):

| Campo   | Tipo | Descripción                            |
| ------- | ---- | -------------------------------------- |
| `audio` | File | Archivo de audio (wav, mp3, ogg, flac, webm) |

> **Límite de subida:** El tamaño máximo del archivo de audio es de **10 MB**. Los archivos más grandes devuelven HTTP 400.

**Respuesta** (JSON):

```json
{
  "transcription": "hello world",
  "duration_sec": 2.35
}
```

### `GET /api/v1/model-info`

Devuelve los metadatos y las capacidades del servicio. **No requiere autenticación.**

**Respuesta** (JSON):

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

## Errores

| Estado | Cuándo |
| --- | --- |
| `400` | Subida vacía o demasiado grande (> 10 MB), formato no admitido, audio demasiado largo (> 30 s) o demasiado corto, texto de referencia vacío, v2: referencia sin palabras pronunciables |
| `401` / `403` | `X-API-Key` ausente / incorrecta |
| `422` | Texto de referencia rechazado por la validación |
| `429` | Límite de peticiones superado (por IP, o por usuario final en [modo interno](internal-integration.md)) |
| `503` | Cola de inferencia llena (`Retry-After`), o archivos del modelo v2 no disponibles |
| `504` | Timeout de la petición (`REQUEST_TIMEOUT_SEC`) |
| `500` | Error inesperado |

## Ejemplo con cURL

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
