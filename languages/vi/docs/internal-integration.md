<!-- doc-id: docs-internal-integration | lang: vi | source-rev: bf352fba -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/internal-integration.md`](../../../docs/internal-integration.md) (rev `bf352fba`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Hướng dẫn tích hợp Microservice nội bộ

> **Đối tượng:** lập trình viên backend tích hợp service của họ với Pronunciation Validation Service này qua mạng nội bộ.

## 1. Vì sao định danh theo từng người dùng quan trọng

Mặc định, service này giới hạn tốc độ **theo IP nguồn**. Khi bạn gọi nó từ một backend khác, mọi người dùng cuối của bạn dùng chung một IP nguồn (container backend của bạn) → 1000 người dùng cùng chia một mức trần 20 req/phút = liên tục nhận 429.

Định danh theo từng người dùng cho phép service giới hạn tốc độ dựa trên danh tính *người dùng cuối thật* mà bạn chuyển tiếp qua một header. Mỗi người dùng cuối có hạn mức riêng; một người dùng spam không bao giờ ảnh hưởng đến những người khác.

---

## 2. Hợp đồng về header

| Header | Bắt buộc khi | Mục đích |
|---|---|---|
| `X-API-Key` | Luôn luôn | Xác thực ở mức service (đã có) |
| `X-Service-Auth` | Khi bạn muốn định danh theo từng người dùng | Phải khớp với biến môi trường `SERVICE_API_KEY` trên service này |
| `X-End-User-Id` | Khi gửi `X-Service-Auth` | Người dùng cuối mà request này thay mặt |

### Yêu cầu về tin cậy

Backend của bạn phải kết nối từ một IP nằm trong `TRUSTED_PROXY_CIDRS_STR` (mặc định: dải RFC1918 của Docker). Trên Coolify, hãy kiểm tra dải mạng của Traefik:

```bash
docker network inspect coolify | grep Subnet
```

### Bảng quyết định: cái gì được dùng làm khóa giới hạn tốc độ

| Peer TCP trực tiếp | Service auth khớp | `X-End-User-Id` hợp lệ | Khóa kết quả |
|---|---|---|---|
| CIDR không tin cậy | (bất kỳ) | (bất kỳ) | `ip:<peer>` |
| CIDR tin cậy       | Không    | (bất kỳ) | `ip:<peer>` |
| CIDR tin cậy       | Có       | Không    | `ip:<peer>` |
| CIDR tin cậy       | Có       | Có       | `user:<id>` ✓ |

> **Chống giả mạo**: cổng tin cậy dùng **peer TCP trực tiếp**, không phải địa chỉ do XFF suy ra. Kẻ tấn công ở `1.2.3.4` không thể giả `X-Forwarded-For: 172.17.0.5` để vượt qua.

---

## 3. Người dùng ẩn danh

Với người dùng chưa đăng nhập (chế độ dùng thử, widget demo, v.v.):

```
X-End-User-Id: anon-<session_id>
```

Trong đó `<session_id>` là một UUID được tạo **phía client** và lưu trong `localStorage`. Một UUID cho mỗi tab trình duyệt.

### Mã giả cho FE

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

> **Không dùng chung UUID giữa các tab**: làm vậy phá vỡ việc cô lập theo từng người dùng. Mỗi tab có UUID riêng.

---

## 4. Wrapper TypeScript (Node 18+ / trình duyệt hiện đại)

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

## 5. Wrapper Python (backend FastAPI / Django)

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

## 6. Ma trận xử lý lỗi

| Trạng thái | Ý nghĩa | Hành động khuyến nghị |
|---|---|---|
| 200 | OK | Dùng nội dung response |
| 400 | Audio không hợp lệ (tệp sai / quá lớn / sai định dạng) | Báo cho người dùng |
| 401 / 403 | Lỗi API key | Báo cho người trực (lỗi cấu hình, không phải lỗi người dùng) |
| 422 | Văn bản tham chiếu bị từ chối (quá dài / có ký tự điều khiển) | Báo cho người dùng |
| 429 | Người dùng này (hoặc BE này) vượt hạn mức | Báo cho người dùng; giảm tốc độ gửi từ UI |
| 500 | Lỗi nội bộ | Thử lại một lần; nếu vẫn lỗi, hiển thị lỗi chung |
| 503 | Hàng đợi suy luận đầy | Tự thử lại với backoff (đã có trong wrapper) |
| 504 | Request hết thời gian (>90s) | Thử lại một lần với đoạn audio nhỏ hơn |

> **Không tự động thử lại 429**: đây là lỗi của người dùng, không phải quá tải server. Tự thử lại chỉ xác nhận lại việc vượt hạn mức và tốn thêm thời gian.

---

## 7. Danh sách kiểm tra (phía BE của sản phẩm)

Chạy trên staging trước khi triển khai production:

- [ ] Request với cả 3 header + `X-End-User-Id` hợp lệ → 200, độ trễ p50 < 500ms
- [ ] Spam 21 request cho **cùng một** `user_id` trong 60s → request thứ 21 trả về 429
- [ ] Spam 21 request qua 21 `user_id` **khác nhau** → tất cả đều 200 (cô lập hoạt động đúng)
- [ ] Giữ hàng đợi suy luận đầy + gửi request → wrapper tự thử lại khi gặp 503 và cuối cùng thành công
- [ ] Bỏ `X-Service-Auth` → xác nhận bạn giờ bị định danh theo IP (5 request cùng IP gần mức trần theo IP)
- [ ] Gửi `X-End-User-Id: evil\nuser` → request vẫn thành công nhưng bị định danh theo IP (fallback khi có ký tự điều khiển)
- [ ] Curl từ một IP không tin cậy với `X-Service-Auth` thật + `X-End-User-Id` của một nạn nhân → bị định danh theo IP của kẻ tấn công, KHÔNG phải nạn nhân (chống giả mạo)

---

## 8. Ghi chú vận hành

### Lưu trữ secret

Lưu `SERVICE_API_KEY` trong trình quản lý secret của bạn (biến môi trường Coolify, AWS Secrets Manager, Vault). Cùng một khóa phải được đặt ở:
- `.env` của service này → `SERVICE_API_KEY=<key>`
- Môi trường của backend bạn → `PRONUNCIATION_SERVICE_AUTH=<key>`

### Xoay khóa (thủ công, v1)

1. Tạo khóa mới: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. Đặt khóa mới trên service này, khởi động lại
3. Đặt khóa mới trên backend của bạn, khởi động lại
4. Có một khoảng ngắn khóa cũ/mới không khớp → các bên gọi tạm thời quay về định danh theo IP (suy giảm nhưng không hỏng)

> **v2 trong tương lai:** xoay khóa mượt, không downtime, qua danh sách chấp nhận chồng lấp.

### Service mesh

Nếu dùng Istio / Linkerd / Consul, hãy đảm bảo chúng không xóa các header tùy chỉnh:
- `X-Service-Auth`
- `X-End-User-Id`

Kiểm tra `headers.allowList` của sidecar hoặc mục tương đương.

### Log

Service này ghi log `client_ip` cho mỗi request (Phase 05 của kế hoạch tối ưu). Khi định danh theo từng người dùng đang hoạt động, trường `client_ip` hiển thị **IP**, không phải user_id: đây là chủ đích, để giữ PII ra khỏi log vận hành.

Để đối chiếu, hãy ghi user_id ở phía **bạn** cùng với nội dung request. Phiên bản sau có thể đưa `request_id` do service sinh ra vào response để bạn có thể nối log.

### Thu hẹp CIDR tin cậy

Giá trị mặc định của `TRUSTED_PROXY_CIDRS_STR` bao phủ mọi dải RFC1918, khá rộng. Để bảo mật chặt hơn, hãy thu hẹp về IP Traefik trên Coolify của bạn:

```bash
docker network inspect coolify | grep Subnet
# e.g., "Subnet": "172.18.0.0/16"
```

Sau đó đặt:
```
TRUSTED_PROXY_CIDRS_STR=172.18.0.0/16
```

---

## 9. Tương thích ngược

Để `SERVICE_API_KEY=""` trên service này sẽ **tắt** định danh theo từng người dùng: mọi bên gọi quay về giới hạn tốc độ theo IP (hành vi hiện có). Có thể triển khai thay đổi phía service trước; các backend áp dụng các header khi sẵn sàng.

---

## 10. Chuyển client sang `/api/v2/evaluate`

Request, xác thực, giới hạn tốc độ và mã lỗi giống hệt v1; chỉ cần trỏ client sang `/api/v2/evaluate`. Trước khi chuyển, hãy kiểm tra điều gì thay đổi với UI của bạn:

- `transcribed_text` là chuỗi IPA nghe được (ví dụ `jɛloʊ wɝd`), không phải các từ được nhận dạng. Đừng hiển thị nó như một câu.
- `is_correct_ipa` là kết luận do bộ chấm học được (F1 chỉ-gắn-cờ 0.54 so với 0.31 của cách heard != expected; trên speechocean762, 18% số phone được nghe khác đi nhưng vẫn được chấp nhận, 0.3% được nghe đúng nhưng vẫn bị gắn cờ). Không bao giờ suy ra "sai" bằng cách so sánh `actual_ipa` với `expected_ipa` trong UI; một phone có thể được nghe thành một ký hiệu khác (`actual_ipa`) mà vẫn được chấp nhận (các biến thể không ảnh hưởng giọng), hoặc được nghe đúng mà vẫn bị gắn cờ.
- Có thêm `start_ms` / `end_ms` cho từng từ để làm nổi bật trong trình phát.
- Điểm số dùng một hiệu chỉnh khác v1: đừng so sánh số của v1 và v2 hoặc dùng lại ngưỡng. Được hiệu chỉnh theo speechocean762 (L1 tiếng Quan Thoại); độ chính xác với các ngôn ngữ mẹ đẻ khác chưa được đo.
- 503 kèm `v2 model is not available on this server.` nghĩa là image được build mà không có các tệp v2.
