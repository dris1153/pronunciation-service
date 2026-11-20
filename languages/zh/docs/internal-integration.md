<!-- doc-id: docs-internal-integration | lang: zh | source-rev: bf352fba -->

> 🌐 **中文翻译**，源文件 [`docs/internal-integration.md`](../../../docs/internal-integration.md)（rev `bf352fba`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# 内部微服务集成指南

> **目标读者：** 通过内部网络将自己的服务与本发音校验服务集成的后端开发者。

## 1. 为什么按用户设置限流键很重要

默认情况下，本服务**按来源 IP** 限流。当你从另一个后端调用它时，你所有的终端用户共用同一个来源 IP（你的后端容器）→ 1000 个用户挤在每分钟 20 次请求的上限下 = 持续不断的 429。

按用户设置限流键，可以让服务根据你通过请求头转发的*真实终端用户*身份进行限流。每个终端用户有自己的配额；某个刷请求的用户永远不会影响其他人。

---

## 2. 请求头约定

| 请求头 | 何时必需 | 用途 |
|---|---|---|
| `X-API-Key` | 始终 | 服务级鉴权（已有） |
| `X-Service-Auth` | 需要按用户设置限流键时 | 必须与本服务上的 `SERVICE_API_KEY` 环境变量一致 |
| `X-End-User-Id` | 发送 `X-Service-Auth` 时 | 本次请求所代表的终端用户 |

### 信任要求

你的后端必须从 `TRUSTED_PROXY_CIDRS_STR` 范围内的 IP 连接（默认：Docker RFC1918）。在 Coolify 上，请确认 Traefik 的网络范围：

```bash
docker network inspect coolify | grep Subnet
```

### 决策表 —— 什么会被用作限流键

| 直连 TCP 对端    | 服务鉴权匹配 | 有效的 `X-End-User-Id` | 最终的键 |
|---|---|---|---|
| 不受信任的 CIDR  | （任意）  | （任意）  | `ip:<peer>` |
| 受信任的 CIDR    | 否     | （任意）  | `ip:<peer>` |
| 受信任的 CIDR    | 是     | 否     | `ip:<peer>` |
| 受信任的 CIDR    | 是     | 是     | `user:<id>` ✓ |

> **防伪造** —— 信任关卡使用的是**直连 TCP 对端**，而不是经 XFF 解析出的地址。位于 `1.2.3.4` 的攻击者无法通过伪造 `X-Forwarded-For: 172.17.0.5` 来绕过。

---

## 3. 匿名用户

对于尚未登录的用户（试用模式、演示组件等）：

```
X-End-User-Id: anon-<session_id>
```

其中 `<session_id>` 是在**客户端**生成并存储在 `localStorage` 中的 UUID。每个浏览器标签页一个 UUID。

### 前端伪代码

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

> **不要在多个标签页之间共用 UUID** —— 这会破坏按用户的隔离。每个标签页使用自己的 UUID。

---

## 4. TypeScript 封装（Node 18+ / 现代浏览器）

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

## 5. Python 封装（FastAPI / Django 后端）

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

## 6. 错误处理矩阵

| 状态码 | 含义 | 建议操作 |
|---|---|---|
| 200 | OK | 使用响应体 |
| 400 | 音频有问题（文件无效 / 过大 / 格式错误） | 提示用户 |
| 401 / 403 | API key 问题 | 通知值班人员（配置错误，不是用户错误） |
| 422 | 参考文本被拒绝（过长 / 含控制字符） | 提示用户 |
| 429 | 该用户（或该后端）超出配额 | 提示用户；对 UI 做节流 |
| 500 | 内部错误 | 重试一次；若持续出现，显示通用错误 |
| 503 | 推理队列已满 | 带退避的自动重试（封装层中已实现） |
| 504 | 请求超时（>90 秒） | 用更小的音频片段重试一次 |

> **不要自动重试 429** —— 这是用户的责任，而不是服务器过载。自动重试只会再次确认配额超限，并浪费更多时间。

---

## 7. 测试清单（产品后端一侧）

在生产上线之前，在预发布环境运行：

- [ ] 带全部 3 个请求头和有效的 `X-End-User-Id` 发送请求 → 200，p50 延迟 < 500ms
- [ ] 对**同一个** `user_id` 在 60 秒内连续发送 21 个请求 → 第 21 个返回 429
- [ ] 用 21 个**不同的** `user_id` 各发送 21 个请求 → 全部 200（隔离生效）
- [ ] 让推理队列保持满载并发送请求 → 封装层在 503 时自动重试并最终成功
- [ ] 省略 `X-Service-Auth` → 确认现在按 IP 作为键（5 个同 IP 请求接近按 IP 的上限）
- [ ] 发送 `X-End-User-Id: evil\nuser` → 请求仍然成功，但按 IP 作为键（控制字符回退）
- [ ] 从不受信任的 IP 用真实的 `X-Service-Auth` + 受害者的 `X-End-User-Id` 执行 curl → 以攻击者的 IP 作为键，而不是受害者（防伪造）

---

## 8. 运维说明

### Secret 存储

将 `SERVICE_API_KEY` 存放在你的 secret 管理器中（Coolify 环境变量、AWS Secrets Manager、Vault）。同一个密钥必须设置在：
- 本服务的 `.env` → `SERVICE_API_KEY=<key>`
- 你的后端的环境变量 → `PRONUNCIATION_SERVICE_AUTH=<key>`

### 密钥轮换（手动，v1）

1. 生成新密钥：`python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. 在本服务上设置新密钥，并重启
3. 在你的后端上设置新密钥，并重启
4. 会有一小段新旧密钥不匹配的窗口 → 调用方暂时回退到按 IP 作为键（性能下降但不会中断）

> **未来的 v2：** 通过重叠的接受列表实现平滑的零停机轮换。

### Service mesh

如果使用 Istio / Linkerd / Consul，请确保它们不会剥离这些自定义请求头：
- `X-Service-Auth`
- `X-End-User-Id`

请检查你的 sidecar 的 `headers.allowList` 或等效配置。

### 日志

本服务对每个请求记录 `client_ip`（优化计划的 Phase 05）。启用按用户设置限流键时，`client_ip` 字段显示的是 **IP**，而不是 user_id —— 这是有意为之，以避免个人身份信息进入运维日志。

如需关联，请在**你自己**这一侧将 user_id 与请求体一起记录。未来的版本可能会在响应中给出服务生成的 `request_id`，以便你进行关联。

### 收窄受信任的 CIDR

默认的 `TRUSTED_PROXY_CIDRS_STR` 覆盖了所有 RFC1918 范围，比较宽松。为了更严格的安全性，请将其收窄到你的 Coolify Traefik IP：

```bash
docker network inspect coolify | grep Subnet
# e.g., "Subnet": "172.18.0.0/16"
```

然后设置：
```
TRUSTED_PROXY_CIDRS_STR=172.18.0.0/16
```

---

## 9. 向后兼容

在本服务上保持 `SERVICE_API_KEY=""` 会**禁用**按用户设置限流键 —— 所有调用方回退到按 IP 限流（现有行为）。可以安全地先发布服务端的改动；后端在准备好后再采用这些请求头。

---

## 10. 将客户端切换到 `/api/v2/evaluate`

请求、鉴权、限流和错误码与 v1 完全相同；只需把客户端指向 `/api/v2/evaluate`。切换之前，请检查你的 UI 会有哪些变化：

- `transcribed_text` 是识别出的 IPA 字符串（例如 `jɛloʊ wɝd`），而不是识别出的单词。不要把它当作句子来渲染。
- `is_correct_ipa` 是学习得到的判定（仅标记时 F1 为 0.54，而“识别出的 != 预期的”为 0.31；在 speechocean762 上，18% 的音素识别结果不同但仍被接受，0.3% 识别正确却被标记）。切勿在 UI 中通过比较 `actual_ipa` 与 `expected_ipa` 来推断“错误”；一个音素可能被识别为不同的符号（`actual_ipa`）却仍被接受（与口音无关的变体），也可能识别正确却被标记。
- 新增的逐单词 `start_ms` / `end_ms`，可用于在播放器中高亮。
- 分数的校准方式与 v1 不同：不要比较 v1 和 v2 的数值，也不要沿用阈值。校准依据是 speechocean762（母语为普通话）；其他母语的准确度尚未测量。
- 返回 503 且消息为 `v2 model is not available on this server.`，表示镜像构建时没有包含 v2 文件。
