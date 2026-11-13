<!-- doc-id: docs-api | lang: ja | source-rev: 78459878 -->

> 🌐 [`docs/api.md`](../../../docs/api.md)（rev `78459878`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# API リファレンス

インタラクティブなドキュメント: `GET /docs`（Swagger UI）と `GET /redoc`。このページは文章形式のリファレンスです。

| エンドポイント | 認証 | 用途 |
| --- | --- | --- |
| `GET /health` | 不要 | 死活監視とモデルのロード済みフラグ |
| `GET /docs` | 不要 | Swagger UI |
| `GET /api/v1/model-info` | 不要 | サービスのメタデータと制限 |
| `POST /api/v1/evaluate` | 必要 | 発音スコア、v1 パイプライン（Wav2Vec2 ASR） |
| `POST /api/v2/evaluate` | 必要 | 発音スコア、v2 パイプライン（音素 CTC + 学習済みスコアラー） |
| `GET /api/v1/text-analysis` | 必要 | テキストから IPA へ変換し、単語ごとの音素を返す |
| `POST /api/v1/transcribe` | 必要 | 音声からテキストへ（v1 ASR）、採点なし |

## 認証

保護されたエンドポイントには `X-API-Key` ヘッダーが必要です。

| 動作               | 条件                                               |
| ------------------ | -------------------------------------------------- |
| 認証は**無効**     | 環境変数 `API_KEY` が空（ローカル開発用の利便性） |
| `401 Unauthorized` | `API_KEY` が設定されているのにヘッダーがない       |
| `403 Forbidden`    | ヘッダーはあるが値が一致しない                     |
| ✅ 処理を続行      | ヘッダーが `API_KEY` と一致                        |

> **注:** `API_KEY` が空の場合、デプロイ前に設定することを促す警告が**起動時に 1 回だけ**（リクエストごとではなく）ログに出力されます。

```bash
# Generate a strong key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

エンドユーザーごとのクォータ、`X-Service-Auth` / `X-End-User-Id` ヘッダー、バックエンドのラッパーについては [internal-integration.md](internal-integration.md) を参照してください。

## エンドポイント

### `GET /health`

ヘルスチェック。サービスの状態とモデルのロード状態を返します。**認証は不要です。**

### `POST /api/v1/evaluate`

発音の品質を評価します。**`X-API-Key` ヘッダーが必要です。**

**リクエスト**（multipart/form-data）:

| フィールド       | 型     | 説明                                   |
| ---------------- | ------ | -------------------------------------- |
| `audio`          | File   | 音声ファイル（wav、mp3、ogg、flac、webm） |
| `reference_text` | string | 話者が言うべきだったテキスト           |

> **アップロード制限:** 音声ファイルの最大サイズは **10 MB** です。これを超えると HTTP 400 を返します。

**レスポンス**（JSON）:

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

リクエスト（multipart: `audio`、`reference_text`）、認証、レート制限、アップロード制限、エラーコードは v1 と同じです。レスポンスは **v1 の形式に単語タイミングを加えたもの**で、スコアは音素レベルのモデルと学習済みスコアラーから得られます。v1 は変更されません。

| フィールド | v2 の動作 |
| --- | --- |
| `results.word_details[].start_ms` / `end_ms` | **新規。** 音声内での単語の位置（ms）。 |
| `transcribed_text` | 認識された**IPA 文字列**で、単語ではありません（単語の ASR はありません）。 |
| `phoneme_details[].actual_ipa` | モデルが認識した音素（空 = 認識されなかった）。 |
| `phoneme_details[].is_correct_ipa` | 学習済みの判定（音素スコアが 2 点満点中 1.48 未満）であり、`actual_ipa == expected_ipa` では**ありません**。speechocean762 のテストでは、音素の 18% は異なる音として認識されても許容され（ɪ/i、ʌ/ɑ のようなアクセント中立の変種）、0.3% は正しく認識されても誤りと判定されます。「練習が必要か」には本フィールドを、「どう聞こえたか」には `actual_ipa` を使用してください。 |
| `phoneme_details[].gop_score` | 0〜100 の音素スコア（学習済みスコア x 50）。 |
| `overall_score`、`accuracy_score`、`fluency_score`、`prosody_score` | 学習済みの予測値を、より厳しい 1 本の曲線 `100 x (s/10)^1.4` で変換したもの。v1 の数値とは比較できません。 |
| `completeness_score` | 期待される音素のうち認識された割合（ルールベースで、学習によるものではありません）。 |
| `error_type` | `Omission`（その単語の音素が 1 つも認識されない）、`Mispronunciation`（単語スコアが 60 未満）、その後、v1 と同様にアライメントされた単語間の隙間から `UnexpectedBreak` / `MissingBreak`。`Insertion` は単語には設定されません（v1 と同じ）。 |

知っておくべき動作:

- デコードできる発話がない音声（無音、ノイズ、別の文。期待される音素の 20% 未満しか認識されない場合）には、推測ではなくゼロスコア応答を返します。
- 発音可能な音素を含まない単語（たとえば単独の `'`）は `word_details` から除外されます。発音可能な単語がない参照テキストには `400` を返します。
- 25 ms より短い音声、または参照テキストをアライメントするには短すぎる音声には `400` を返します。
- サーバーに v2 のモデルファイルがない場合、エンドポイントは `503` を返し、v1 は引き続き動作します。

モデルと採点の詳細: [scoring-v2.md](scoring-v2.md)。クライアントを v1 から移行する方法: [internal-integration.md](internal-integration.md#10-クライアントを-apiv2evaluate-に切り替える)。

<details>
<summary>レスポンス例（サニティクリップ「yellow word」を「hello world」に対して採点した実際の出力）</summary>

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

英語のテキストを解析して IPA に変換し、単語ごとの音素の内訳を返します。**`X-API-Key` ヘッダーが必要です。**

**クエリパラメータ:**

| パラメータ | 型     | 説明                                  |
| ------ | ------ | ------------------------------------- |
| `text` | string | 解析する英語テキスト（1〜500 文字）   |

**レスポンス**（JSON）:

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

音声をアップロードして、プレーンテキストの書き起こしを取得します（採点なし）。**`X-API-Key` ヘッダーが必要です。**

**リクエスト**（multipart/form-data）:

| フィールド | 型   | 説明                                   |
| ------- | ---- | -------------------------------------- |
| `audio` | File | 音声ファイル（wav、mp3、ogg、flac、webm） |

> **アップロード制限:** 音声ファイルの最大サイズは **10 MB** です。これを超えると HTTP 400 を返します。

**レスポンス**（JSON）:

```json
{
  "transcription": "hello world",
  "duration_sec": 2.35
}
```

### `GET /api/v1/model-info`

サービスのメタデータと機能を返します。**認証は不要です。**

**レスポンス**（JSON）:

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

## エラー

| ステータス | 発生条件 |
| --- | --- |
| `400` | アップロードが空または大きすぎる（> 10 MB）、未対応の形式、音声が長すぎる（> 30 秒）または短すぎる、参照テキストが空、v2: 発音可能な単語がない参照テキスト |
| `401` / `403` | `X-API-Key` がない / 誤っている |
| `422` | 参照テキストが検証で拒否された |
| `429` | レート制限を超過（IP ごと、または[内部モード](internal-integration.md)ではエンドユーザーごと） |
| `503` | 推論キューが満杯（`Retry-After`）、または v2 のモデルファイルが利用できない |
| `504` | リクエストのタイムアウト（`REQUEST_TIMEOUT_SEC`） |
| `500` | 予期しないエラー |

## cURL の例

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
