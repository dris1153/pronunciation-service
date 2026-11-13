<!-- doc-id: docs-workflow | lang: vi | source-rev: b030953c -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/workflow.md`](../../../docs/workflow.md) (rev `b030953c`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Luồng làm việc và luồng xử lý request

> Pronunciation Validation Service: request đi qua hệ thống như thế nào, xác thực hoạt động ra sao, triển khai được thiết lập thế nào.
> Mục 1-2 mô tả pipeline **v1**; sơ đồ v1 so với v2, trình tự xử lý một request v2 và khởi động nằm trong [architecture.md](architecture.md).

---

## 1. Tổng quan kiến trúc

```
┌──────────┐     ┌──────────────────────┐      ┌─────────────────────────┐
│  Client  │────▶│   FastAPI API         │────▶│  PronunciationService   │
│ (audio + │     │  /api/v1/evaluate     │      │  (orchestrator)         │
│  text)   │     │  /api/v1/text-analysis│      └──┬──────┬──────┬──────┬─┘
└──────────┘     │  /api/v1/transcribe   │         │      │      │      │
                 │  /api/v1/model-info   │         ▼      ▼      ▼      ▼
                 └──────────────────────┘    ┌──────┐ ┌────┐ ┌────┐ ┌───────┐
                                             │  ASR │ │IPA │ │GOP │ │Prosody│
                                             │  Svc │ │Svc │ │Svc │ │  Svc  │
                                             └──┬───┘ └──┬─┘ └──┬─┘ └───┬───┘
                                                │        │      │       │
                                           Wav2Vec2   g2p_en  CTC    librosa
                                           model     + NLTK  log-    pyin
                                                             posts
```

---

## 2. Luồng request (POST /api/v1/evaluate)

```
Client                  FastAPI                PronunciationService        ASR / IPA / GOP
  │                       │                           │                          │
  │── POST audio+text ──▶ │                          │                          │
  │   + X-API-Key header  │                           │                          │
  │                       │── verify_api_key() ──▶ ✓ │                          │
  │                       │── validate audio type     │                          │
  │                       │── read audio bytes        │                          │
  │                       │                           │                          │
  │                       │── svc.evaluate() ────────▶│                         │
  │                       │                           │── load_audio_from_bytes()
  │                       │                           │── validate_audio_duration()
  │                       │                           │── normalize_audio()      │
  │                       │                           │                          │
  │                       │                           │── asr.get_emission() ─▶ │ Wav2Vec2 (1 pass)
  │                       │                           │◀── emission ─────────── │
  │                       │                           │── asr.decode(emission)   │
  │                       │                           │   → transcription        │
  │                       │                           │                          │
  │                       │                           │── ipa.to_ipa() ───────▶ │ g2p_en
  │                       │                           │◀── ref_ipa + act_ipa ── │
  │                       │                           │── compare phonemes       │
  │                       │                           │                          │
  │                       │                           │── gop.score(emission) ▶ │ reuses emission
  │                       │                           │◀── gop_result ───────── │
  │                       │                           │                         │
  │                       │                           │── combined_score        │
  │                       │                           │   accuracy = 0.55×IPA   │
  │                       │                           │            + 0.45×GOP   │
  │                       │                           │   completeness =        │
  │                       │                           │     accuracy-weighted   │
  │                       │                           │     ratio of ref words  │
  │                       │                           │   fluency = 0.4×rate    │
  │                       │                           │          + 0.6×pause    │
  │                       │                           │   prosody = 0.55×int    │
  │                       │                           │     + 0.20×spd+0.25×rhy│
  │                       │                           │   overall = 0.4×s0      │
  │                       │                           │    + 0.2×s1+0.2×s2     │
  │                       │                           │          + 0.2×s3       │
  │                       │                           │── error_type per word   │
  │                       │                           │   (+ break detection)   │
  │                       │                           │── level + feedback      │
  │                       │                          │                          │
  │                       │◀── PronunciationResponse ─│                         │
  │◀── JSON response ────│                           │                          │
```

### Từng bước

| #   | Bước                     | Thành phần             | Mô tả                                                                                                                                                               |
| --- | ------------------------ | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | **Xác thực**             | `dependencies.py`      | Kiểm tra header `X-API-Key` (bỏ qua nếu `API_KEY` để trống)                                                                                                         |
| 2   | **Kiểm tra đầu vào**     | `pronunciation.py`     | Kiểm tra content type của audio, kích thước tệp (≤10 MB) và văn bản tham chiếu không rỗng                                                                           |
| 3   | **Nạp audio**            | `utils/audio.py`       | Giải mã byte audio → mảng numpy 16 kHz mono float32 (librosa)                                                                                                       |
| 4   | **Phiên âm**             | `ASRService`           | Model Wav2Vec2 tạo văn bản từ giọng nói                                                                                                                             |
| 5   | **Lọc từ đệm**           | `utils/text.py`        | Loại bỏ các từ ngập ngừng (uh, um, hmm…) qua `filter_fillers(text_to_words(...))`                                                                                   |
| 6   | **Chuyển đổi IPA**       | `IPAService`           | Cả văn bản tham chiếu và bản phiên âm → chuỗi phoneme IPA                                                                                                           |
| 7   | **So sánh IPA**          | `PronunciationService` | Căn chỉnh và so sánh phoneme kỳ vọng với phoneme thực tế, tính độ chính xác                                                                                         |
| 8   | **Chấm GOP**             | `GOPService`           | Kiểm tra im lặng → log hậu nghiệm CTC → căn chỉnh cưỡng bức → GOP theo từng phoneme + thời gian                                                                     |
| 9   | **Phân tích ngữ điệu**   | `ProsodyService`       | Trích xuất cao độ (pyin) → chấm phương sai, khoảng, đường nét → phát hiện giọng đều đều                                                                             |
| 10  | **Phân loại lỗi**        | `PronunciationService` | Loại lỗi theo từng từ: None / Mispronunciation / Omission / Insertion / UnexpectedBreak / MissingBreak                                                              |
| 11  | **Điểm thành phần**      | `PronunciationService` | `accuracy_score` = 55% IPA + 45% GOP; `completeness_score` = tỷ lệ có trọng số theo độ chính xác; `fluency_score` = tốc độ + quãng ngắt; `prosody_score` = ngữ điệu lên xuống + tốc độ + nhịp điệu |
| 12  | **Chấm điểm cuối**       | `PronunciationService` | Overall = 0.4×s0 + 0.2×s1 + 0.2×s2 + 0.2×s3 (4 điểm thành phần sắp xếp từ thấp→cao)                                                                                 |
| 13  | **Response**             | `pronunciation.py`     | Trả về JSON `PronunciationResponse` kèm mức đánh giá và nhận xét                                                                                                    |

---

### Luồng request v2 (POST /api/v2/evaluate)

Cùng cách kiểm tra đầu vào, xác thực, giới hạn tốc độ và semaphore suy luận như v1 (`app/api/upload.py`), sau đó, không dùng torch:
giải mã audio → ONNX phone CTC (frame 20 ms) → căn chỉnh cưỡng bức CTC bằng numpy → đặc trưng GOP theo từng phone + phone nghe được → bộ chấm học từ dữ liệu
(MLP phone → ridge cho từ/câu nói) → response dạng v1 kèm thời gian từng từ. Lỗi ngắt quãng dùng lại quy tắc quãng ngắt của v1 trên các khoảng từ đã căn chỉnh.

## 3. Luồng xác thực

```
Request with X-API-Key header
            │
            ▼
   ┌─── API_KEY set? ───┐
   │                     │
   No                   Yes
   │                     │
   ▼                     ▼
 SKIP auth        ┌── Header present? ──┐
 (dev mode)       │                     │
                  No                   Yes
                  │                     │
                  ▼                     ▼
              401 Unauthorized    ┌── Key matches? ──┐
                                  │                   │
                                  No                 Yes
                                  │                   │
                                  ▼                   ▼
                              403 Forbidden       ✅ Proceed
```

| Endpoint                    | Yêu cầu xác thực                     |
| --------------------------- | ------------------------------------ |
| `GET /health`               | ❌ Không — công khai cho health check |
| `GET /docs`                 | ❌ Không — Swagger UI                |
| `GET /redoc`                | ❌ Không — ReDoc UI                  |
| `GET /api/v1/model-info`    | ❌ Không — metadata dịch vụ công khai |
| `POST /api/v1/evaluate`     | ✅ Có — yêu cầu header `X-API-Key`   |
| `GET /api/v1/text-analysis` | ✅ Có — yêu cầu header `X-API-Key`   |
| `POST /api/v1/transcribe`   | ✅ Có — yêu cầu header `X-API-Key`   |

---

## 4. Khởi động ứng dụng (Lifespan)

```
uvicorn starts
    │
    ▼
create_app()
    │── configure FastAPI (title, version, docs)
    │── register_middleware (CORS, exception handlers)
    │── include_router (health, pronunciation, ipa, transcribe, model_info)
    │
    ▼
lifespan() — async context manager
    │── setup_logging()
    │── get_settings()           ← load .env via absolute path
    │── check ffmpeg available   ← needed for MP3/OGG/WebM decoding
    │── get_asr_service()        ← download/load Wav2Vec2 model
    │── get_ipa_service()        ← init g2p_en + NLTK data
    │── get_gop_service()        ← init GOP scorer
    │── get_prosody_service()    ← init prosody analyser
    │── log "All models loaded ✓"
    │
    ▼
Application is ready to serve requests
    │
    ▼ (on shutdown)
    └── log "Shutting down …"
```

---

## 5. Các luồng triển khai

### 5a. Railway (Production)

```
git push to Railway
    │
    ▼
Railway reads railway.toml
    │── builder = "dockerfile"
    │── healthcheckPath = "/health"
    │── healthcheckTimeout = 120
    │── restartPolicyType = "on_failure"
    │
    ▼
Docker build
    │── python:3.11-slim base
    │── install ffmpeg, libsndfile1
    │── pip install CPU-only PyTorch (torch+cpu from PyTorch CPU index)
    │── pip install requirements.txt
    │── ENV ASR_MODEL_NAME (set before RUN — build-arg override works)
    │── BAKE Wav2Vec2 model into image  ← no persistent volumes on Railway
    │── ENV PORT=8000 (default; Railway overrides at runtime)
    │
    ▼
CMD ["python", "main.py"]
    │── pydantic-settings reads PORT env var → Settings.port
    │── uvicorn binds to 0.0.0.0:$PORT
    │
    ▼
Railway health check → GET /health
    │── Returns { status: "ok", version, model_loaded }
```

**Điểm chính:**

- Railway gán `PORT` lúc chạy: pydantic-settings đọc nó trực tiếp (không cần shell mở rộng `$PORT`)
- Model được **đóng sẵn** vào Docker image lúc build (Railway không có volume lưu trữ bền vững)
- `ENV ASR_MODEL_NAME` được đặt **trước** bước `RUN` tải model để việc ghi đè bằng `--build-arg` hoạt động
- Biến môi trường (`API_KEY`, `ASR_MODEL_NAME`, v.v.) được đặt trong Railway Dashboard
- `railway.toml` có `healthcheckPath = "/health"` và `healthcheckTimeout = 120`
- Không có `startCommand`: dùng trực tiếp CMD từ Dockerfile

---

## 6. Hệ thống chấm điểm

Các công thức v1 (độ chính xác, độ đầy đủ, độ trôi chảy, ngữ điệu, điểm tổng, loại lỗi) nằm trong [scoring-v1.md](scoring-v1.md); cách chấm điểm thuần phoneme của v2 nằm trong [scoring-v2.md](scoring-v2.md).

---

## 7. Định dạng audio được hỗ trợ

| Định dạng | MIME Type                                |
| --------- | ---------------------------------------- |
| WAV       | `audio/wav`, `audio/x-wav`, `audio/wave` |
| MP3       | `audio/mpeg`, `audio/mp3`                |
| OGG       | `audio/ogg`                              |
| FLAC      | `audio/flac`                             |
| WebM      | `audio/webm`                             |

Mọi audio đều được chuyển thành mảng numpy **16 kHz mono float32** qua librosa.

---

## 8. Schema response của API

Schema response và ví dụ cho mọi endpoint, v1 và v2: [api.md](api.md).

---

## 9. Benchmark tài nguyên

Độ trễ và bộ nhớ đã đo cho v1, v2 FP32 và v2 INT8: [evaluation.md](evaluation.md). Định cỡ tài nguyên và quy tắc lúc chạy: [deployment.md](deployment.md).
