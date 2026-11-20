<!-- doc-id: docs-configuration | lang: es | source-rev: 1c1e2cda -->

> 🌐 **Traducción al español** de [`docs/configuration.md`](../../../docs/configuration.md) (rev `1c1e2cda`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Configuración

Todos los ajustes son variables de entorno (o entradas en `.env`, resueltas desde la raíz del proyecto). Los nombres no distinguen mayúsculas de minúsculas. La plantilla es [`.env.example`](../../../.env.example); la fuente de verdad es [`app/core/config.py`](../../../app/core/config.py).

> `.env` solo acepta los nombres que aparecen abajo. Una clave desconocida (un error tipográfico, o valores solo de build como `V2_MODEL_REPO`) hace que el arranque falle con `extra_forbidden`. Pon los valores solo de build en el entorno de build, no en `.env`.

## Aplicación

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `APP_NAME` | `Pronunciation Validator` | Se muestra en OpenAPI y en `model-info` |
| `APP_VERSION` | `1.0.0` | Se muestra en OpenAPI, `/health` y `model-info` |
| `APP_HOST` | `0.0.0.0` | Dirección de enlace |
| `PORT` | `8000` | Puerto del servidor (Railway lo inyecta en tiempo de ejecución) |
| `DEBUG` | `false` | `true` omite la validación de robustez de la API key y usa logs legibles. Siempre `false` en producción |
| `LOG_LEVEL` | `INFO` | Nivel de log. Con `DEBUG=false` se escribe una línea JSON por registro |

## Modelos v1 (Wav2Vec2)

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `ASR_MODEL_NAME` | `facebook/wav2vec2-base-960h` | Id del modelo en Hugging Face. `...-large-960h-lv60-self` es más preciso con acentos, pero pesa ~1.2 GB y tarda ~7 s por clip |
| `ASR_MODEL_CACHE_DIR` | `./model_cache` | Caché del modelo |
| `DEVICE` | `cpu` | `cpu` o `cuda` |
| `INFERENCE_BACKEND` | `torch_fp32` | `torch_fp32` o `torch_int8` (INT8 dinámico para el ASR v1) |

## Modelo de fonemas v2

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `PHONE_MODEL_DIR` | `./data/models/hubert-phone-ctc` | Directorio con `model.int8.onnx` (y opcionalmente `model.onnx`), `vocab.json`, `scorer.json` |
| `PHONE_MODEL_INT8` | `true` | `true` carga `model.int8.onnx` (~116 MB, ~3x más rápido); `false` carga `model.onnx` (FP32, ~360 MB) |

Si faltan archivos o no se pueden leer, `/api/v2/evaluate` responde `503`; v1 no se ve afectado. Cómo llegan los archivos a una imagen: [deployment.md](deployment.md).

## Audio

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `AUDIO_SAMPLE_RATE` | `16000` | Frecuencia de muestreo del modelo (Hz). Ambos pipelines asumen 16 kHz |
| `AUDIO_MAX_DURATION_SEC` | `30` | El audio más largo se rechaza con `400` |

El límite de tamaño de subida (10 MB) y los tipos MIME aceptados son constantes en `app/core/constants.py`.

## Seguridad

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `API_KEY` | _(vacío)_ | `X-API-Key` de los endpoints protegidos. Obligatoria cuando `DEBUG=false`: al menos 32 caracteres y que no figure en la lista de claves débiles. Para generarla: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SERVICE_API_KEY` | _(vacío)_ | Activa el límite de peticiones por usuario final para un backend de confianza (`X-Service-Auth`). Consulta [internal-integration.md](internal-integration.md) |
| `TRUSTED_PROXY_CIDRS_STR` | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | Pares cuyo `X-Forwarded-For` es de confianza. Redúcelo a tu proxy |
| `CORS_ORIGINS_STR` | `*` | Orígenes separados por comas (o un array JSON). `*` es solo para desarrollo |

## Límite de peticiones, timeouts y concurrencia

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | Interruptor general (desactívalo en las pruebas y en CI) |
| `RATE_LIMIT_EVALUATE_PER_MINUTE` | `20` | Límite para cada una de `/api/v1/evaluate` y `/api/v2/evaluate` (cada ruta lleva su propio contador) |
| `RATE_LIMIT_TRANSCRIBE_PER_MINUTE` | `15` | |
| `RATE_LIMIT_TEXT_ANALYSIS_PER_MINUTE` | `120` | |
| `REQUEST_TIMEOUT_SEC` | `90` | Las peticiones más largas devuelven `504` |
| `MAX_CONCURRENT_INFERENCES` | `0` | Huecos de inferencia. `0` = automático (núcleos - 1, con un máximo de 4). Hilos por hueco = núcleos / huecos. Medido: 4 vCPU -> `2`; 2 vCPU -> automático (1 hueco) |
| `INFERENCE_QUEUE_TIMEOUT_SEC` | `60` | Tiempo que una petición puede esperar un hueco antes de recibir `503` con `Retry-After` |

Con `--cpus` de Docker o en Railway, la cuota de CPU es invisible para la sonda de afinidad; define `OMP_NUM_THREADS` con el número de vCPU y prevalece sobre el valor calculado.

## Prosodia (solo v1)

| Variable | Valor por defecto | Descripción |
| --- | --- | --- |
| `PROSODY_PITCH_MIN_HZ` / `PROSODY_PITCH_MAX_HZ` | `65` / `600` | Rango de búsqueda de pyin |
| `PROSODY_MONOTONE_THRESHOLD` | `0.08` | Un coeficiente de variación del tono por debajo de este valor es monótono |
| `PROSODY_PITCH_CV_UPPER` | `0.25` | Un CV igual o superior a este valor puntúa 100. Debe ser mayor que el umbral de monotonía |

## Solo en tiempo de build (no se leen de `.env`)

| Nombre | Dónde | Descripción |
| --- | --- | --- |
| `V2_MODEL_REPO` | Argumento de build de Docker / variable de build de nixpacks | Repo público de Hugging Face con los archivos v2, por ejemplo `dris1153/pronunciation-v2` |
| `HF_TOKEN` | Secreto de build de Docker (`--secret id=HF_TOKEN,env=HF_TOKEN`) / variable de build de nixpacks | Solo hace falta si ese repo es privado: un token de lectura. Nunca lo subas al repositorio ni lo incluyas en una capa de la imagen |
| `ASR_MODEL_NAME` | Argumento de build de Docker | Sustituye el modelo v1 incluido en la imagen |
