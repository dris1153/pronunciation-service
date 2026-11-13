<!-- doc-id: docs-internal-integration | lang: es | source-rev: 59ec0cbb -->

> 🌐 **Traducción al español** de [`docs/internal-integration.md`](../../../docs/internal-integration.md) (rev `59ec0cbb`). La versión en inglés es la oficial: si difieren, prevalece el inglés. Traducción automática, sin revisión de un hablante nativo.

# Guía de integración de microservicios internos

> **Público:** desarrolladores de backend que integran su servicio con este Pronunciation Validation Service a través de una red interna.

## 1. Por qué importa la clave por usuario

Por defecto, este servicio limita las peticiones **por IP de origen**. Cuando lo llamas desde otro backend, todos tus usuarios finales comparten la misma IP de origen (el contenedor de tu backend) → 1000 usuarios compitiendo contra un tope de 20 pet./min = 429 constantes.

La clave por usuario permite que el servicio limite las peticiones según la identidad del *usuario final real* que reenvías en una cabecera. Cada usuario final tiene su propia cuota; un usuario que abusa nunca afecta a los demás.

---

## 2. Contrato de cabeceras

| Cabecera | Obligatoria cuando | Propósito |
|---|---|---|
| `X-API-Key` | Siempre | Autenticación a nivel de servicio (ya existente) |
| `X-Service-Auth` | Cuando quieres clave por usuario | Debe coincidir con la variable de entorno `SERVICE_API_KEY` de este servicio |
| `X-End-User-Id` | Cuando envías `X-Service-Auth` | El usuario final en cuyo nombre se hace esta petición |

### Requisitos de confianza

Tu backend debe conectarse desde una IP dentro de `TRUSTED_PROXY_CIDRS_STR` (por defecto: RFC1918 de Docker). En Coolify, verifica el rango de red de Traefik:

```bash
docker network inspect coolify | grep Subnet
```

### Tabla de decisión — qué se usa como clave del límite de peticiones

| Par TCP directo  | Auth de servicio coincide | `X-End-User-Id` válido | Clave resultante |
|---|---|---|---|
| CIDR no confiable | (cualquiera) | (cualquiera) | `ip:<peer>` |
| CIDR confiable   | No     | (cualquiera) | `ip:<peer>` |
| CIDR confiable   | Sí     | No     | `ip:<peer>` |
| CIDR confiable   | Sí     | Sí     | `user:<id>` ✓ |

> **A prueba de suplantación** — la compuerta de confianza usa el **par TCP directo**, no la dirección resuelta a partir de XFF. Un atacante en `1.2.3.4` no puede falsificar `X-Forwarded-For: 172.17.0.5` para eludirla.

---

## 3. Usuarios anónimos

Para los usuarios que no han iniciado sesión (modo de prueba, widgets de demostración, etc.):

```
X-End-User-Id: anon-<session_id>
```

Donde `<session_id>` es un UUID generado **en el cliente** y guardado en `localStorage`. Un UUID por pestaña del navegador.

### Pseudocódigo del FE

```javascript
function getOrCreateAnonId() {
  let id = localStorage.getItem("pronun_anon_id");
  if (!id) {
    id = `anon-${crypto.randomUUID()}`;
    localStorage.setItem("pronun_anon_id", id);
  }
  return id;
}

// Forward to your BE in every request body / cookie / header
```

> **No compartas UUID entre pestañas** — anula el aislamiento por usuario. Cada pestaña tiene el suyo.

---

## 4. Wrapper de TypeScript (Node 18+ / navegadores modernos)

```typescript
// pronunciationClient.ts
const SERVICE_URL = process.env.PRONUNCIATION_URL!;
const API_KEY = process.env.PRONUNCIATION_API_KEY!;
const SERVICE_AUTH = process.env.PRONUNCIATION_SERVICE_AUTH!;

interface CallOptions {
  audio: Buffer | Blob;
  referenceText: string;
  userId: string;            // session.userId OR anon-<uuid>
  audioMime?: string;        // default "audio/wav"
}

export class RateLimitError extends Error {}
export class ServiceUnavailableError extends Error {}

const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));

export async function evaluatePronunciation(opts: CallOptions) {
  const headers: Record<string, string> = {
    "X-API-Key": API_KEY,
    "X-Service-Auth": SERVICE_AUTH,
    "X-End-User-Id": opts.userId,
  };

  const formData = new FormData();
  const blob = opts.audio instanceof Blob
    ? opts.audio
    : new Blob([opts.audio], { type: opts.audioMime ?? "audio/wav" });
  formData.append("audio", blob, "audio.wav");
  formData.append("reference_text", opts.referenceText);

  const MAX_RETRIES = 3;
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const resp = await fetch(`${SERVICE_URL}/api/v1/evaluate`, {
      method: "POST",
      headers,
      body: formData,
    });

    if (resp.status === 503) {
      // Inference queue full — auto-retry with exponential backoff (capped by Retry-After)
      const retryAfter = Number(resp.headers.get("retry-after") ?? "1");
      const delay = Math.min(Math.pow(2, attempt) * 1000, retryAfter * 1000);
      await sleep(delay);
      continue;
    }

    if (resp.status === 429) {
      // Per-user quota exceeded — propagate to caller, do NOT silently retry
      throw new RateLimitError("End-user has exceeded pronunciation quota");
    }

    if (!resp.ok) {
      const text = await resp.text();
      throw new Error(`Pronunciation service ${resp.status}: ${text}`);
    }

    return await resp.json();
  }
  throw new ServiceUnavailableError("Pronunciation service unavailable after 3 retries");
}
```

---

## 5. Wrapper de Python (backends FastAPI / Django)

```python
import asyncio
import os

import httpx

PRONUNCIATION_URL = os.environ["PRONUNCIATION_URL"]
API_KEY = os.environ["PRONUNCIATION_API_KEY"]
SERVICE_AUTH = os.environ["PRONUNCIATION_SERVICE_AUTH"]


class RateLimitError(Exception):
    pass


class ServiceUnavailableError(Exception):
    pass


async def evaluate_pronunciation(
    audio: bytes,
    reference_text: str,
    user_id: str,
    audio_mime: str = "audio/wav",
) -> dict:
    headers = {
        "X-API-Key": API_KEY,
        "X-Service-Auth": SERVICE_AUTH,
        "X-End-User-Id": user_id,
    }
    files = {"audio": ("audio.wav", audio, audio_mime)}
    data = {"reference_text": reference_text}

    async with httpx.AsyncClient(timeout=120.0) as client:
        for attempt in range(3):
            resp = await client.post(
                f"{PRONUNCIATION_URL}/api/v1/evaluate",
                headers=headers, files=files, data=data,
            )
            if resp.status_code == 503:
                retry_after = int(resp.headers.get("retry-after", "1"))
                delay = min(2 ** attempt, retry_after)
                await asyncio.sleep(delay)
                continue
            if resp.status_code == 429:
                raise RateLimitError("End-user pronunciation quota exceeded")
            resp.raise_for_status()
            return resp.json()

    raise ServiceUnavailableError("Pronunciation service unavailable after 3 retries")
```

---

## 6. Matriz de manejo de errores

| Estado | Significado | Acción recomendada |
|---|---|---|
| 200 | OK | Usar el cuerpo de la respuesta |
| 400 | Audio incorrecto (archivo no válido / demasiado grande / formato erróneo) | Mostrárselo al usuario |
| 401 / 403 | Problema con la API key | Avisar a la guardia (error de configuración, no del usuario) |
| 422 | Texto de referencia rechazado (demasiado largo / caracteres de control) | Mostrárselo al usuario |
| 429 | Este usuario (o este BE) superó la cuota | Mostrárselo al usuario; limitar la UI |
| 500 | Error interno | Reintentar una vez; si persiste, mostrar un error genérico |
| 503 | Cola de inferencia llena | Reintento automático con backoff (ya incluido en el wrapper) |
| 504 | Timeout de la petición (>90s) | Reintentar una vez con un fragmento de audio más pequeño |

> **No reintentes 429 automáticamente** — es culpa del usuario, no una sobrecarga del servidor. Reintentar solo confirma la cuota y pierde más tiempo.

---

## 7. Lista de comprobación de pruebas (lado BE del producto)

Ejecútala en staging antes del despliegue a producción:

- [ ] Petición con las 3 cabeceras + `X-End-User-Id` válido → 200, latencia p50 < 500ms
- [ ] Enviar en masa 21 peticiones del **mismo** `user_id` en 60s → la 21.ª devuelve 429
- [ ] Enviar en masa 21 peticiones con 21 `user_id` **distintos** → todas 200 (el aislamiento funciona)
- [ ] Mantener llena la cola de inferencia + enviar una petición → el wrapper reintenta automáticamente ante 503 y al final lo consigue
- [ ] Omitir `X-Service-Auth` → confirmar que ahora la clave es la IP (5 peticiones de la misma IP cerca del tope por IP)
- [ ] Enviar `X-End-User-Id: evil\nuser` → la petición sigue funcionando pero la clave es la IP (alternativa por carácter de control)
- [ ] Curl desde una IP no confiable con el `X-Service-Auth` real + el `X-End-User-Id` de una víctima → la clave es la IP del atacante, NO la de la víctima (prevención de suplantación)

---

## 8. Notas operativas

### Almacenamiento de secretos

Guarda `SERVICE_API_KEY` en tu gestor de secretos (variables de entorno de Coolify, AWS Secrets Manager, Vault). La misma clave debe definirse en:
- El `.env` de este servicio → `SERVICE_API_KEY=<key>`
- El entorno de tu backend → `PRONUNCIATION_SERVICE_AUTH=<key>`

### Rotación de claves (manual, v1)

1. Genera una clave nueva: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Define la clave nueva en este servicio y reinícialo
3. Define la clave nueva en tu backend y reinícialo
4. Breve ventana en la que las claves antigua y nueva no coinciden → los llamadores vuelven temporalmente a la clave por IP (degradado, pero sin romperse)

> **v2 futura:** rotación gradual sin tiempo de inactividad mediante una lista de claves aceptadas solapadas.

### Service mesh

Si usas Istio / Linkerd / Consul, asegúrate de que no eliminen las cabeceras personalizadas:
- `X-Service-Auth`
- `X-End-User-Id`

Revisa el `headers.allowList` de tu sidecar o el equivalente.

### Logs

Este servicio registra `client_ip` en cada petición (Fase 05 del plan de optimización). Cuando la clave por usuario está activa, el campo `client_ip` muestra la **IP**, no el user_id — a propósito, para mantener los datos personales fuera de los logs de operaciones.

Para correlacionar, registra el user_id en **tu** lado junto con el cuerpo de la petición. Una revisión futura podría exponer en la respuesta el `request_id` generado por el servicio para que puedas cruzar los datos.

### Reducción de los CIDR confiables

El valor por defecto de `TRUSTED_PROXY_CIDRS_STR` cubre todos los rangos RFC1918, lo cual es permisivo. Para mayor seguridad, redúcelo a la IP de Traefik de tu Coolify:

```bash
docker network inspect coolify | grep Subnet
# e.g., "Subnet": "172.18.0.0/16"
```

Después define:
```
TRUSTED_PROXY_CIDRS_STR=172.18.0.0/16
```

---

## 9. Compatibilidad hacia atrás

Dejar `SERVICE_API_KEY=""` en este servicio **desactiva** la clave por usuario — todos los llamadores vuelven al límite por IP (comportamiento existente). Es seguro desplegar primero el cambio del lado del servicio; los backends adoptan las cabeceras cuando estén listos.

---

## 10. Migrar un cliente a `/api/v2/evaluate`

La petición, la autenticación, el límite de peticiones y los códigos de error son idénticos a v1; solo tienes que apuntar el cliente a `/api/v2/evaluate`. Antes de migrar, comprueba qué cambia para tu UI:

- `transcribed_text` es la cadena IPA oída (p. ej. `jɛloʊ wɝd`), no las palabras reconocidas. No la muestres como una oración.
- `is_correct_ipa` es un veredicto aprendido (F1 solo del marcado 0.54 frente a 0.31 con oído != esperado; en speechocean762, el 18% de los fonemas se oyen distintos pero se aceptan, el 0.3% se oyen correctos pero se marcan). Nunca deduzcas "incorrecto" comparando `actual_ipa` con `expected_ipa` en la UI; un fonema puede oírse como otro símbolo (`actual_ipa`) y aun así aceptarse (variantes neutras en cuanto al acento), o oírse correctamente y marcarse.
- Nuevos `start_ms` / `end_ms` por palabra para resaltar en un reproductor.
- Las puntuaciones tienen una calibración distinta a la de v1: no compares los números de v1 y v2 ni reutilices umbrales. Calibrado con speechocean762 (L1 mandarín); la precisión con L1 vietnamita aún no se ha medido.
- Un 503 con `v2 model is not available on this server.` significa que la imagen se construyó sin los archivos v2.
