# Internal Microservice Integration Guide

> **Audience:** backend developers integrating their service with this Pronunciation Validation Service over an internal network.

## 1. Why per-user keying matters

By default, this service rate-limits **per source IP**. When you call it from another backend, all your end-users share the same source IP (your backend container) → 1000 users gathering against a 20 req/min cap = constant 429s.

Per-user keying lets the service rate-limit on the *real end-user* identity that you forward in a header. Each end-user gets their own quota; one spammy user never affects the others.

---

## 2. Headers contract

| Header | Required when | Purpose |
|---|---|---|
| `X-API-Key` | Always | Service-level auth (existing) |
| `X-Service-Auth` | When you want per-user keying | Must match `SERVICE_API_KEY` env on this service |
| `X-End-User-Id` | When sending `X-Service-Auth` | The end-user this request is on behalf of |

### Trust requirements

Your backend must connect from an IP within `TRUSTED_PROXY_CIDRS_STR` (default: Docker RFC1918). On Coolify, verify the Traefik network range:

```bash
docker network inspect coolify | grep Subnet
```

### Decision table — what gets used as the rate-limit key

| Direct TCP peer  | Service auth match | Valid `X-End-User-Id` | Resulting key |
|---|---|---|---|
| Untrusted CIDR   | (any)  | (any)  | `ip:<peer>` |
| Trusted CIDR     | No     | (any)  | `ip:<peer>` |
| Trusted CIDR     | Yes    | No     | `ip:<peer>` |
| Trusted CIDR     | Yes    | Yes    | `user:<id>` ✓ |

> **Spoof-safe** — trust gate uses the **direct TCP peer**, not the XFF-resolved address. An attacker on `1.2.3.4` cannot forge `X-Forwarded-For: 172.17.0.5` to bypass.

---

## 3. Anonymous users

For users who haven't logged in (trial mode, demo widgets, etc.):

```
X-End-User-Id: anon-<session_id>
```

Where `<session_id>` is a UUID generated **client-side** and stored in `localStorage`. One UUID per browser tab.

### FE pseudo-code

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

> **Don't share UUIDs across tabs** — defeats the per-user isolation. Each tab gets its own.

---

## 4. TypeScript wrapper (Node 18+ / modern browsers)

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

## 5. Python wrapper (FastAPI / Django backends)

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

## 6. Error-handling matrix

| Status | Meaning | Recommended action |
|---|---|---|
| 200 | OK | Use response body |
| 400 | Bad audio (invalid file / oversized / wrong format) | Surface to user |
| 401 / 403 | API key issue | Page on-call (config bug, not user error) |
| 422 | Reference text rejected (too long / control chars) | Surface to user |
| 429 | This user (or this BE) exceeded quota | Surface to user; throttle UI |
| 500 | Internal error | Retry once; if persists, surface generic error |
| 503 | Inference queue full | Auto-retry with backoff (already in wrapper) |
| 504 | Request timeout (>90s) | Retry once with smaller audio chunk |

> **Don't auto-retry 429** — it's user-fault, not server overload. Auto-retrying just confirms the quota and burns more time.

---

## 7. Testing checklist (Product BE side)

Run on staging before production rollout:

- [ ] Request with all 3 headers + valid `X-End-User-Id` → 200, p50 latency < 500ms
- [ ] Spam 21 requests for the **same** `user_id` within 60s → the 21st returns 429
- [ ] Spam 21 requests across 21 **different** `user_id`s → all 200 (isolation works)
- [ ] Hold inference queue full + send request → wrapper auto-retries on 503 and eventually succeeds
- [ ] Omit `X-Service-Auth` → confirm you're now keyed by IP (5 same-IP requests near the per-IP cap)
- [ ] Send `X-End-User-Id: evil\nuser` → request still succeeds but is keyed by IP (control-char fallback)
- [ ] Curl from a non-trusted IP with the real `X-Service-Auth` + a victim's `X-End-User-Id` → keyed by attacker IP, NOT the victim (spoof-prevention)

---

## 8. Operational notes

### Secret storage

Store `SERVICE_API_KEY` in your secret manager (Coolify env vars, AWS Secrets Manager, Vault). The same key must be set on:
- This service's `.env` → `SERVICE_API_KEY=<key>`
- Your backend's env → `PRONUNCIATION_SERVICE_AUTH=<key>`

### Key rotation (manual, v1)

1. Generate new key: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Set new key on this service, restart
3. Set new key on your backend, restart
4. Brief window where old/new keys mismatch → callers temporarily fall back to per-IP keying (degraded but not broken)

> **Future v2:** graceful zero-downtime rotation via overlapping accept-list.

### Service mesh

If using Istio / Linkerd / Consul, ensure they don't strip the custom headers:
- `X-Service-Auth`
- `X-End-User-Id`

Check your sidecar's `headers.allowList` or equivalent.

### Logs

This service logs `client_ip` per request (Phase 05 of optimization plan). When per-user keying is active, the `client_ip` field shows the **IP**, not the user_id — by design, to keep PII out of ops logs.

To correlate, log the user_id on **your** side along with the request body. Future revision may surface the service-generated `request_id` in the response so you can join.

### Trusted-CIDR narrowing

The default `TRUSTED_PROXY_CIDRS_STR` covers all RFC1918 ranges, which is permissive. For tighter security, narrow to your Coolify Traefik IP:

```bash
docker network inspect coolify | grep Subnet
# e.g., "Subnet": "172.18.0.0/16"
```

Then set:
```
TRUSTED_PROXY_CIDRS_STR=172.18.0.0/16
```

---

## 9. Backward compatibility

Leaving `SERVICE_API_KEY=""` on this service **disables** per-user keying — all callers fall back to per-IP rate limiting (existing behaviour). Safe to roll out the service-side change first; backends adopt the headers when ready.

---

## 10. Switching a client to `/api/v2/evaluate`

Request, auth, rate limit and error codes are identical to v1; only point the client at `/api/v2/evaluate`. Before switching check what changes for your UI:

- `transcribed_text` is the heard IPA string (e.g. `jɛloʊ wɝd`), not the recognised words. Don't render it as a sentence.
- `is_correct_ipa` is a learned verdict (flag-only F1 0.54 vs 0.31 for heard != expected; on speechocean762, 18% of phones are heard differently yet accepted, 0.3% heard correctly yet flagged). Never derive "wrong" by comparing `actual_ipa` with `expected_ipa` in the UI; a phone can be heard as a different symbol (`actual_ipa`) and still be accepted (accent-neutral variants), or heard correctly and flagged.
- New per-word `start_ms` / `end_ms` for highlighting in a player.
- Scores are on a different calibration than v1: do not compare v1 and v2 numbers or reuse thresholds. Calibrated against speechocean762 (Mandarin L1); Vietnamese-L1 accuracy has not been measured yet.
- 503 with `v2 model is not available on this server.` means the image was built without the v2 files.
