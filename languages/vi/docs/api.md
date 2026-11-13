<!-- doc-id: docs-api | lang: vi | source-rev: 78459878 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/api.md`](../../../docs/api.md) (rev `78459878`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Tham chiếu API

Tài liệu tương tác: `GET /docs` (Swagger UI) và `GET /redoc`. Trang này là bản tham chiếu viết tay.

| Endpoint | Xác thực | Mục đích |
| --- | --- | --- |
| `GET /health` | không | Kiểm tra dịch vụ còn sống và cờ model đã tải |
| `GET /docs` | không | Swagger UI |
| `GET /api/v1/model-info` | không | Metadata và giới hạn của dịch vụ |
| `POST /api/v1/evaluate` | có | Điểm phát âm, pipeline v1 (Wav2Vec2 ASR) |
| `POST /api/v2/evaluate` | có | Điểm phát âm, pipeline v2 (phone CTC + bộ chấm học từ dữ liệu) |
| `GET /api/v1/text-analysis` | có | Văn bản sang IPA kèm các phoneme của từng từ |
| `POST /api/v1/transcribe` | có | Audio sang văn bản (ASR v1), không chấm điểm |

## Xác thực

Các endpoint được bảo vệ yêu cầu header `X-API-Key`.

| Hành vi            | Điều kiện                                          |
| ------------------ | -------------------------------------------------- |
| Xác thực **tắt**   | Biến môi trường `API_KEY` để trống (tiện cho dev local) |
| `401 Unauthorized` | Thiếu header khi `API_KEY` đã được đặt             |
| `403 Forbidden`    | Có header nhưng giá trị không khớp                 |
| ✅ Cho qua         | Header khớp với `API_KEY`                          |

> **Lưu ý:** Khi `API_KEY` để trống, một cảnh báo được ghi log **một lần lúc khởi động** (không phải mỗi request) để nhắc bạn đặt nó trước khi triển khai.

```bash
# Generate a strong key
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Hạn mức theo từng người dùng cuối, các header `X-Service-Auth` / `X-End-User-Id` và các wrapper phía backend: xem [internal-integration.md](internal-integration.md).

## Endpoint

### `GET /health`

Kiểm tra sức khỏe: trả về trạng thái dịch vụ và trạng thái tải model. **Không cần xác thực.**

### `POST /api/v1/evaluate`

Đánh giá chất lượng phát âm. **Yêu cầu header `X-API-Key`.**

**Request** (multipart/form-data):

| Trường           | Kiểu   | Mô tả                                  |
| ---------------- | ------ | -------------------------------------- |
| `audio`          | File   | Tệp audio (wav, mp3, ogg, flac, webm)  |
| `reference_text` | string | Văn bản mà người nói lẽ ra phải đọc    |

> **Giới hạn tải lên:** Kích thước tệp audio tối đa là **10 MB**. Tệp lớn hơn trả về HTTP 400.

**Response** (JSON):

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

Cùng request (multipart: `audio`, `reference_text`), cùng xác thực, giới hạn tốc độ, giới hạn tải lên và mã lỗi như v1. Response có **dạng của v1 cộng thêm thời gian từng từ**; điểm số đến từ một model mức phoneme và một bộ chấm học từ dữ liệu. v1 không thay đổi.

| Trường | Hành vi của v2 |
| --- | --- |
| `results.word_details[].start_ms` / `end_ms` | **Mới.** Vị trí của từ trong audio (ms). |
| `transcribed_text` | **Chuỗi IPA** nghe được, không phải các từ (không có ASR mức từ). |
| `phoneme_details[].actual_ipa` | Phone mà model nghe được (rỗng = không nghe thấy). |
| `phoneme_details[].is_correct_ipa` | Kết luận do bộ chấm học được (điểm phone < 1.48 trên thang 2), **không** phải `actual_ipa == expected_ipa`. Trên tập test speechocean762, 18% số phone được nghe khác đi nhưng vẫn được chấp nhận (các biến thể không ảnh hưởng giọng như ɪ/i, ʌ/ɑ) và 0.3% được nghe đúng nhưng vẫn bị đánh dấu. Dùng nó cho "cần luyện thêm"; dùng `actual_ipa` cho "nghe giống gì". |
| `phoneme_details[].gop_score` | Điểm phone trên thang 0-100 (điểm học được x 50). |
| `overall_score`, `accuracy_score`, `fluency_score`, `prosody_score` | Các dự đoán của bộ chấm học được, ánh xạ qua một đường cong chặt hơn, `100 x (s/10)^1.4`. Không so sánh được với số liệu của v1. |
| `completeness_score` | Tỷ lệ phone kỳ vọng đã được nghe thấy (theo quy tắc, không phải học được). |
| `error_type` | `Omission` (không nghe thấy phone nào của từ), `Mispronunciation` (điểm từ < 60), sau đó là `UnexpectedBreak` / `MissingBreak` từ các khoảng trống giữa các từ đã căn chỉnh, như v1. `Insertion` không bao giờ được gán cho từ (giống v1). |

Những hành vi đáng biết:

- Audio không có tiếng nói giải mã được (im lặng, nhiễu, một câu khác; nghe thấy ít hơn 20% số phone kỳ vọng) trả về phản hồi điểm 0 thay vì đoán.
- Các từ không chứa phone nào phát âm được (ví dụ một dấu `'` đơn lẻ) bị loại khỏi `word_details`; văn bản tham chiếu không có từ nào phát âm được trả về `400`.
- Audio ngắn hơn 25 ms, hoặc quá ngắn để căn chỉnh với văn bản tham chiếu, trả về `400`.
- Nếu các tệp model v2 không có trên server, endpoint trả về `503` và v1 vẫn hoạt động.

Chi tiết về model và cách chấm điểm: [scoring-v2.md](scoring-v2.md). Chuyển client từ v1: [internal-integration.md](internal-integration.md#10-chuyển-client-sang-apiv2evaluate).

<details>
<summary>Response ví dụ (đầu ra thật cho clip sanity "yellow word" được chấm với "hello world")</summary>

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

Phân tích văn bản tiếng Anh và chuyển sang IPA kèm bảng phân rã phoneme của từng từ. **Yêu cầu header `X-API-Key`.**

**Tham số query:**

| Tham số | Kiểu   | Mô tả                                       |
| ------- | ------ | ------------------------------------------- |
| `text`  | string | Văn bản tiếng Anh cần phân tích (1–500 ký tự) |

**Response** (JSON):

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

Tải audio lên và nhận bản phiên âm dạng văn bản thuần (không chấm điểm). **Yêu cầu header `X-API-Key`.**

**Request** (multipart/form-data):

| Trường  | Kiểu | Mô tả                                  |
| ------- | ---- | -------------------------------------- |
| `audio` | File | Tệp audio (wav, mp3, ogg, flac, webm)  |

> **Giới hạn tải lên:** Kích thước tệp audio tối đa là **10 MB**. Tệp lớn hơn trả về HTTP 400.

**Response** (JSON):

```json
{
  "transcription": "hello world",
  "duration_sec": 2.35
}
```

### `GET /api/v1/model-info`

Trả về metadata và khả năng của dịch vụ. **Không cần xác thực.**

**Response** (JSON):

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

## Lỗi

| Trạng thái | Khi nào |
| --- | --- |
| `400` | Tải lên rỗng hoặc quá lớn (> 10 MB), định dạng không được hỗ trợ, audio quá dài (> 30 s) hoặc quá ngắn, văn bản tham chiếu rỗng, v2: văn bản tham chiếu không có từ nào phát âm được |
| `401` / `403` | Thiếu / sai `X-API-Key` |
| `422` | Văn bản tham chiếu bị bước kiểm tra hợp lệ từ chối |
| `429` | Vượt giới hạn tốc độ (theo IP, hoặc theo người dùng cuối trong [chế độ nội bộ](internal-integration.md)) |
| `503` | Hàng đợi suy luận đầy (`Retry-After`), hoặc không có các tệp model v2 |
| `504` | Request hết thời gian (`REQUEST_TIMEOUT_SEC`) |
| `500` | Lỗi không mong đợi |

## Ví dụ cURL

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
