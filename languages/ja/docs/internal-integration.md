<!-- doc-id: docs-internal-integration | lang: ja | source-rev: 59ec0cbb -->

> 🌐 [`docs/internal-integration.md`](../../../docs/internal-integration.md)（rev `59ec0cbb`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# 内部マイクロサービス連携ガイド

> **対象読者:** 社内ネットワーク経由で自分のサービスをこの発音検証サービスに連携させるバックエンド開発者。

## 1. ユーザーごとのキー設定が重要な理由

デフォルトでは、このサービスは**送信元 IP ごとに**レート制限をかけます。別のバックエンドから呼び出す場合、エンドユーザー全員が同じ送信元 IP（あなたのバックエンドのコンテナ）を共有するため、1000 人のユーザーが 20 req/分の上限に集中して、常に 429 が返ることになります。

ユーザーごとのキー設定を使うと、ヘッダーで転送された*実際のエンドユーザー*の識別子に基づいてレート制限をかけられます。各エンドユーザーが自分専用のクォータを持つため、乱用するユーザーが 1 人いても他のユーザーには影響しません。

---

## 2. ヘッダーの仕様

| ヘッダー | 必須となる場合 | 用途 |
|---|---|---|
| `X-API-Key` | 常に | サービスレベルの認証（既存） |
| `X-Service-Auth` | ユーザーごとのキー設定を使う場合 | このサービスの環境変数 `SERVICE_API_KEY` と一致している必要がある |
| `X-End-User-Id` | `X-Service-Auth` を送る場合 | このリクエストの対象となるエンドユーザー |

### 信頼の要件

バックエンドは `TRUSTED_PROXY_CIDRS_STR`（デフォルト: Docker の RFC1918）の範囲内の IP から接続する必要があります。Coolify では、Traefik のネットワーク範囲を確認してください。

```bash
docker network inspect coolify | grep Subnet
```

### 判定表 — レート制限のキーとして使われるもの

| 直接の TCP ピア  | サービス認証の一致 | 有効な `X-End-User-Id` | 結果のキー |
|---|---|---|---|
| 信頼されない CIDR   | （問わない）  | （問わない）  | `ip:<peer>` |
| 信頼される CIDR     | なし     | （問わない）  | `ip:<peer>` |
| 信頼される CIDR     | あり    | なし     | `ip:<peer>` |
| 信頼される CIDR     | あり    | あり    | `user:<id>` ✓ |

> **なりすまし対策済み** — 信頼ゲートは XFF から解決されたアドレスではなく、**直接の TCP ピア**を使います。`1.2.3.4` の攻撃者が `X-Forwarded-For: 172.17.0.5` を偽装して回避することはできません。

---

## 3. 匿名ユーザー

ログインしていないユーザー（トライアルモード、デモウィジェットなど）の場合:

```
X-End-User-Id: anon-<session_id>
```

`<session_id>` は**クライアント側**で生成した UUID で、`localStorage` に保存します。ブラウザのタブごとに 1 つの UUID を使います。

### FE の疑似コード

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

> **UUID をタブ間で共有しないでください** — ユーザーごとの分離が意味を失います。タブごとに独自の UUID を持たせてください。

---

## 4. TypeScript ラッパー（Node 18+ / モダンブラウザ）

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

## 5. Python ラッパー（FastAPI / Django バックエンド）

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

## 6. エラー処理の対応表

| ステータス | 意味 | 推奨される対応 |
|---|---|---|
| 200 | OK | レスポンスボディを使用する |
| 400 | 音声が不正（無効なファイル / サイズ超過 / 形式違い） | ユーザーに伝える |
| 401 / 403 | API キーの問題 | オンコール担当に通知する（ユーザーのミスではなく設定のバグ） |
| 422 | 参照テキストが拒否された（長すぎる / 制御文字） | ユーザーに伝える |
| 429 | このユーザー（またはこの BE）がクォータを超過 | ユーザーに伝え、UI でスロットリングする |
| 500 | 内部エラー | 1 回リトライし、解消しなければ汎用的なエラーを伝える |
| 503 | 推論キューが満杯 | バックオフ付きで自動リトライする（ラッパーに実装済み） |
| 504 | リクエストのタイムアウト（>90 秒） | 音声チャンクを小さくして 1 回リトライする |

> **429 は自動リトライしないでください** — サーバーの過負荷ではなく、ユーザー側の原因によるものです。自動でリトライしても、クォータ超過を再確認して時間を浪費するだけです。

---

## 7. テストチェックリスト（プロダクト BE 側）

本番へのロールアウト前に、ステージングで実行してください。

- [ ] 3 つのヘッダーすべてと有効な `X-End-User-Id` 付きのリクエスト → 200、p50 レイテンシ < 500ms
- [ ] **同じ** `user_id` で 60 秒以内に 21 件のリクエストを連続送信 → 21 件目が 429 を返す
- [ ] 21 個の**異なる** `user_id` で 21 件のリクエストを送信 → すべて 200（分離が機能している）
- [ ] 推論キューを満杯にしたままリクエストを送信 → ラッパーが 503 で自動リトライし、最終的に成功する
- [ ] `X-Service-Auth` を省略 → IP でキー設定されることを確認（同一 IP の 5 件のリクエストが IP ごとの上限に近づく）
- [ ] `X-End-User-Id: evil\nuser` を送信 → リクエストは成功するが、IP でキー設定される（制御文字のフォールバック）
- [ ] 信頼されない IP から、本物の `X-Service-Auth` と被害者の `X-End-User-Id` を付けて curl → 被害者ではなく攻撃者の IP でキー設定される（なりすまし防止）

---

## 8. 運用上の注意

### シークレットの保管

`SERVICE_API_KEY` はシークレットマネージャー（Coolify の環境変数、AWS Secrets Manager、Vault）に保管してください。同じキーを次の両方に設定する必要があります。
- このサービスの `.env` → `SERVICE_API_KEY=<key>`
- あなたのバックエンドの環境変数 → `PRONUNCIATION_SERVICE_AUTH=<key>`

### キーのローテーション（手動、v1）

1. 新しいキーを生成する: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. このサービスに新しいキーを設定し、再起動する
3. あなたのバックエンドに新しいキーを設定し、再起動する
4. 新旧のキーが一致しない短い期間は、呼び出し元が一時的に IP ごとのキー設定にフォールバックする（性能は低下するが動作はする）

> **今後の v2:** 受け入れリストを重複させることで、ダウンタイムなしの円滑なローテーションを実現する予定。

### サービスメッシュ

Istio / Linkerd / Consul を使う場合は、次のカスタムヘッダーが削除されないようにしてください。
- `X-Service-Auth`
- `X-End-User-Id`

サイドカーの `headers.allowList` またはそれに相当する設定を確認してください。

### ログ

このサービスはリクエストごとに `client_ip` をログに記録します（最適化計画のフェーズ 05）。ユーザーごとのキー設定が有効な場合でも、`client_ip` フィールドには user_id ではなく **IP** が表示されます。これは運用ログに個人情報を含めないための意図的な仕様です。

突き合わせるには、**自分の側**でリクエストボディとともに user_id をログに記録してください。今後の改訂で、サービスが生成した `request_id` をレスポンスに含め、結合できるようにする可能性があります。

### 信頼する CIDR の絞り込み

デフォルトの `TRUSTED_PROXY_CIDRS_STR` は RFC1918 の全範囲を含むため、緩い設定です。セキュリティを強化するには、Coolify の Traefik の IP に絞り込んでください。

```bash
docker network inspect coolify | grep Subnet
# e.g., "Subnet": "172.18.0.0/16"
```

その後、次のように設定します。
```
TRUSTED_PROXY_CIDRS_STR=172.18.0.0/16
```

---

## 9. 後方互換性

このサービスで `SERVICE_API_KEY=""` のままにしておくと、ユーザーごとのキー設定は**無効**になり、すべての呼び出し元が IP ごとのレート制限（既存の動作）にフォールバックします。サービス側の変更を先にロールアウトしても安全で、バックエンドは準備ができた時点でヘッダーを採用できます。

---

## 10. クライアントを `/api/v2/evaluate` に切り替える

リクエスト、認証、レート制限、エラーコードは v1 と同一です。クライアントの向き先を `/api/v2/evaluate` に変えるだけです。切り替える前に、UI にとって何が変わるかを確認してください。

- `transcribed_text` は、認識された単語ではなく、認識された IPA 文字列（例: `jɛloʊ wɝd`）です。文として表示しないでください。
- `is_correct_ipa` は学習済みの判定です（フラグのみの F1 は 0.54 で、認識された音 != 期待される音の場合の 0.31 を上回ります。speechocean762 では、音素の 18% は異なる音として認識されても許容され、0.3% は正しく認識されても誤りと判定されます）。UI で `actual_ipa` と `expected_ipa` を比較して「誤り」を導出しないでください。音素は異なる記号（`actual_ipa`）として認識されても許容されることがあり（アクセント中立の変種）、正しく認識されても誤りと判定されることがあります。
- 単語ごとに `start_ms` / `end_ms` が新たに追加されました。プレーヤーでのハイライトに使えます。
- スコアは v1 とは異なるキャリブレーションです。v1 と v2 の数値を比較したり、しきい値を流用したりしないでください。speechocean762（中国語が母語）に対してキャリブレーションされており、ベトナム語を母語とする話者での正確さはまだ測定されていません。
- `v2 model is not available on this server.` を伴う 503 は、v2 のファイルなしでイメージがビルドされたことを意味します。
