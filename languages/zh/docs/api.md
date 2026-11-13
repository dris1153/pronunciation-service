<!-- doc-id: docs-api | lang: zh | source-rev: 78459878 -->

> 🌐 **中文翻译**，源文件 [`docs/api.md`](../../../docs/api.md)（rev `78459878`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# API 参考

交互式文档：`GET /docs`（Swagger UI）和 `GET /redoc`。本页是文字版参考。

| 端点 | 鉴权 | 用途 |
| --- | --- | --- |
| `GET /health` | 否 | 存活检查和模型已加载标志 |
| `GET /docs` | 否 | Swagger UI |
| `GET /api/v1/model-info` | 否 | 服务元数据和限制 |
| `POST /api/v1/evaluate` | 是 | 发音评分，v1 流水线（Wav2Vec2 ASR） |
| `POST /api/v2/evaluate` | 是 | 发音评分，v2 流水线（音素 CTC + 学习式评分器） |
| `GET /api/v1/text-analysis` | 是 | 文本转 IPA，含逐单词音素 |
| `POST /api/v1/transcribe` | 是 | 音频转文本（v1 ASR），不评分 |

## 鉴权

受保护的端点需要 `X-API-Key` 请求头。

| 行为               | 条件                                               |
| ------------------ | -------------------------------------------------- |
| 鉴权**关闭**       | `API_KEY` 环境变量为空（方便本地开发）             |
| `401 Unauthorized` | 设置了 `API_KEY` 但缺少请求头                      |
| `403 Forbidden`    | 有请求头但值不匹配                                 |
| ✅ 放行            | 请求头与 `API_KEY` 匹配                            |

> **注意：** `API_KEY` 为空时，会在**启动时记录一次**警告（而不是每个请求都记录），提醒你在部署前设置它。

```bash
# Generate a strong key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

按终端用户的配额、`X-Service-Auth` / `X-End-User-Id` 请求头以及后端封装层：见 [internal-integration.md](internal-integration.md)。

## 端点

### `GET /health`

健康检查，返回服务状态和模型加载状态。**无需鉴权。**

### `POST /api/v1/evaluate`

评估发音质量。**需要 `X-API-Key` 请求头。**

**请求**（multipart/form-data）：

| 字段             | 类型   | 说明                                   |
| ---------------- | ------ | -------------------------------------- |
| `audio`          | File   | 音频文件（wav、mp3、ogg、flac、webm）  |
| `reference_text` | string | 说话人本应说出的文本                   |

> **上传限制：** 音频文件最大 **10 MB**。更大的文件返回 HTTP 400。

**响应**（JSON）：

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

请求相同（multipart：`audio`、`reference_text`），鉴权、限流、上传限制和错误码也与 v1 相同。响应是 **v1 的结构加上单词时间戳**；评分来自音素级模型和学习式评分器。v1 保持不变。

| 字段 | v2 行为 |
| --- | --- |
| `results.word_details[].start_ms` / `end_ms` | **新增。** 单词在音频中的位置（毫秒）。 |
| `transcribed_text` | 识别出的 **IPA 字符串**，而不是单词（没有单词 ASR）。 |
| `phoneme_details[].actual_ipa` | 模型识别出的音素（空 = 未识别到）。 |
| `phoneme_details[].is_correct_ipa` | 学习得到的判定（音素得分 < 1.48，满分 2），**不是** `actual_ipa == expected_ipa`。在 speechocean762 测试集上，18% 的音素识别结果不同但仍被接受（与口音无关的变体，如 ɪ/i、ʌ/ɑ），0.3% 识别正确却被标记为错误。用它判断“需要练习”；用 `actual_ipa` 看“听起来像什么”。 |
| `phoneme_details[].gop_score` | 0-100 的音素得分（学习得分 x 50）。 |
| `overall_score`、`accuracy_score`、`fluency_score`、`prosody_score` | 学习得到的预测值，经同一条更严格的曲线 `100 x (s/10)^1.4` 映射。与 v1 的数值不可比较。 |
| `completeness_score` | 被识别到的预期音素所占比例（规则，不是学习得到的）。 |
| `error_type` | `Omission`（该单词没有识别到任何音素）、`Mispronunciation`（单词得分 < 60），然后是根据对齐后的单词间隙得出的 `UnexpectedBreak` / `MissingBreak`，与 v1 相同。单词上从不设置 `Insertion`（与 v1 相同）。 |

值得了解的行为：

- 没有可解码语音的音频（静音、噪声、说了另一句话；识别到的预期音素少于 20%）会返回零分响应，而不是猜测一个结果。
- 不含可发音音素的单词（例如单独的 `'`）不会出现在 `word_details` 中；参考文本中没有任何可发音单词时返回 `400`。
- 短于 25 ms 的音频，或短到无法与参考文本对齐的音频，返回 `400`。
- 如果服务器上没有 v2 模型文件，该端点返回 `503`，v1 继续正常工作。

模型和评分的细节：[scoring-v2.md](scoring-v2.md)。将客户端从 v1 迁移：[internal-integration.md](internal-integration.md#10-将客户端切换到-apiv2evaluate)。

<details>
<summary>示例响应（健全性测试音频 "yellow word" 对照 "hello world" 评分的真实输出）</summary>

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

分析英文文本并转换为 IPA，同时给出逐单词的音素拆分。**需要 `X-API-Key` 请求头。**

**查询参数：**

| 参数   | 类型   | 说明                                  |
| ------ | ------ | ------------------------------------- |
| `text` | string | 要分析的英文文本（1–500 个字符）      |

**响应**（JSON）：

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

上传音频并获得纯文本转写（不评分）。**需要 `X-API-Key` 请求头。**

**请求**（multipart/form-data）：

| 字段    | 类型 | 说明                                   |
| ------- | ---- | -------------------------------------- |
| `audio` | File | 音频文件（wav、mp3、ogg、flac、webm）  |

> **上传限制：** 音频文件最大 **10 MB**。更大的文件返回 HTTP 400。

**响应**（JSON）：

```json
{
  "transcription": "hello world",
  "duration_sec": 2.35
}
```

### `GET /api/v1/model-info`

返回服务元数据和能力。**无需鉴权。**

**响应**（JSON）：

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

## 错误

| 状态码 | 触发条件 |
| --- | --- |
| `400` | 上传为空或过大（> 10 MB）、格式不支持、音频过长（> 30 秒）或过短、参考文本为空、v2：参考文本中没有可发音的单词 |
| `401` / `403` | 缺少 / 错误的 `X-API-Key` |
| `422` | 参考文本未通过校验 |
| `429` | 超出限流（按 IP，或在[内部模式](internal-integration.md)下按终端用户） |
| `503` | 推理队列已满（`Retry-After`），或 v2 模型文件不可用 |
| `504` | 请求超时（`REQUEST_TIMEOUT_SEC`） |
| `500` | 意外错误 |

## cURL 示例

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
