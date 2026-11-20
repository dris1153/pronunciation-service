<!-- doc-id: docs-architecture | lang: vi | source-rev: ec588fa9 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/architecture.md`](../../../docs/architecture.md) (rev `ec588fa9`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Kiến trúc

## Tổng quan hệ thống

```mermaid
flowchart LR
    client["Client / backend của sản phẩm"] -->|"audio + reference_text<br/>X-API-Key"| mw
    subgraph svc["Dịch vụ FastAPI (một tiến trình, một worker)"]
        mw["Middleware<br/>CORS, giới hạn tốc độ, timeout, request id"] --> val["Xác thực + kiểm tra tệp tải lên<br/>app/api/upload.py"]
        val --> sem["Semaphore suy luận<br/>hàng đợi, 503 khi đầy"]
        sem --> v1["Pipeline v1<br/>Wav2Vec2 ASR, g2p, GOP, pyin"]
        sem --> v2["Pipeline v2<br/>ONNX phone CTC, đặc trưng GOP, bộ chấm học từ dữ liệu"]
        mw --> misc["text-analysis, transcribe,<br/>model-info, health"]
    end
    v1 --> w1[("Trọng số Wav2Vec2<br/>đóng sẵn trong image")]
    v2 --> w2[("model.int8.onnx, vocab.json, scorer.json<br/>từ repo HF lúc build")]
```

Mọi thứ chạy trong một tiến trình vì các model lớn và chỉ được tải một lần; thêm worker uvicorn sẽ khiến mỗi worker tải một bản sao riêng. Suy luận trên CPU bị giới hạn bởi một semaphore (`MAX_CONCURRENT_INFERENCES`), và phần việc chặn chạy trong một worker thread để event loop luôn rảnh.

## v1 và v2 cạnh nhau

```mermaid
flowchart TB
    subgraph V1["v1 (/api/v1/evaluate)"]
        direction TB
        a1["Audio"] --> b1["Wav2Vec2 ASR<br/>chữ cái A-Z"]
        b1 --> c1["Bản phiên âm"]
        c1 --> d1["g2p ra IPA, căn chỉnh văn bản<br/>độ chính xác IPA"]
        b1 --> e1["Căn chỉnh cưỡng bức CTC trên hậu nghiệm chữ cái<br/>GOP"]
        a1 --> f1["Cao độ pyin<br/>ngữ điệu"]
        d1 --> g1["Công thức tinh chỉnh thủ công<br/>điểm thành phần kiểu Azure"]
        e1 --> g1
        f1 --> g1
    end
    subgraph V2["v2 (/api/v2/evaluate)"]
        direction TB
        a2["Audio"] --> b2["HuBERT phone CTC<br/>41 phone IPA"]
        t2["Văn bản tham chiếu"] --> c2["g2p ra các phone kỳ vọng"]
        b2 --> d2["Căn chỉnh cưỡng bức các<br/>phone kỳ vọng"]
        c2 --> d2
        d2 --> e2["Đặc trưng GOP + phone nghe được"]
        e2 --> f2["Bộ chấm học từ dữ liệu<br/>huấn luyện trên điểm chuyên gia"]
    end
```

| | v1 | v2 |
| --- | --- | --- |
| Đơn vị được chấm | các từ do ASR nhận ra | từng phone kỳ vọng |
| Bằng chứng ở mức phone | hậu nghiệm chữ cái | hậu nghiệm phone |
| Điểm số | công thức (55% IPA + 45% GOP, điểm tổng lấy theo sorted-min) | học từ điểm chuyên gia của speechocean762 |
| Ngữ điệu / độ trôi chảy | cao độ pyin, tốc độ nói, quãng ngắt | học từ các đặc trưng căn chỉnh (không có bộ theo dõi cao độ) |
| Runtime | PyTorch | ONNX Runtime (INT8), không có PyTorch trong code v2 |
| Độ trễ p50 (clip 3.4 s, 4 vCPU) | 381 ms | 125 ms |

## Một request v2

```mermaid
sequenceDiagram
    participant C as Client
    participant R as Route /api/v2/evaluate
    participant Q as Semaphore suy luận
    participant S as Dịch vụ V2 (worker thread)
    participant O as Model phone ONNX
    participant Sc as Bộ chấm
    C->>R: audio, reference_text, X-API-Key
    R->>R: giới hạn tốc độ, API key, kiểm tra văn bản, kích thước, MIME, thời lượng
    alt đầu vào không hợp lệ
        R-->>C: 400 / 401 / 403 / 422 / 429
    end
    R->>R: lấy dịch vụ V2
    alt thiếu hoặc hỏng tệp model
        R-->>C: 503
    end
    R->>Q: chờ một slot (tối đa 60 s)
    alt hết thời gian chờ hàng đợi
        Q-->>C: 503 Retry-After
    end
    Q->>S: chạy trong thread
    S->>S: giải mã audio, kiểm tra im lặng
    S->>O: dạng sóng
    O-->>S: log hậu nghiệm
    S->>S: căn chỉnh phone kỳ vọng, đặc trưng GOP, phone nghe được
    alt im lặng, hoặc nghe thấy dưới 20% số phone kỳ vọng
        S-->>C: 200 phản hồi điểm 0
    else có tiếng nói
        S->>Sc: đặc trưng theo từng phone
        Sc-->>S: điểm phone, từ, câu nói
        S-->>C: 200 response kèm start_ms / end_ms của từng từ
    end
```

Lỗi giá trị từ dịch vụ (audio quá ngắn, văn bản tham chiếu không có từ nào phát âm được) trở thành `400`; mọi lỗi không mong đợi trở thành `500` với thông báo chung chung.

## Khởi động

```mermaid
flowchart TD
    s0["lifespan bắt đầu"] --> s1["Kiểm tra TMPDIR và các thư mục cache ghi được"]
    s1 --> s2["Đặt số thread của torch (trừ khi có OMP_NUM_THREADS)"]
    s2 --> s3["Cảnh báo nếu API_KEY trống"]
    s3 --> s4["Tải trước v1: ASR, IPA, GOP, ngữ điệu"]
    s4 --> s5{"Tải trước v2"}
    s5 -->|ok| s6["Kiểm tra ffmpeg"]
    s5 -->|"có lỗi bất kỳ"| s5w["Ghi log cảnh báo, /api/v2 trả 503"] --> s6
    s6 --> s7["Phục vụ request"]
```

Model v1 hỏng sẽ dừng quá trình khởi động; model v2 hỏng hoặc thiếu thì không bao giờ làm vậy.

## Cách tổ chức code

```
app/
  application.py            FastAPI factory + lifespan (model preload)
  api/
    routes/                 health, ipa, model_info, pronunciation (v1), pronunciation_v2, transcribe
    dependencies.py         API key, service lookup (v1, v2 with 503)
    middleware.py           CORS, rate limit, timeout, exception handlers
    upload.py               upload + reference text validation shared by v1 and v2
  core/                     config (pydantic-settings), concurrency, constants, logging
  models/schemas.py         Pydantic schemas (v1 and additive V2 subclasses)
  services/
    pronunciation_service.py  v1 orchestrator
    asr_service.py, gop_service.py, ipa_service.py, prosody_service.py   v1 components
    phoneme_align.py        phone similarity groups + DP alignment (no torch, shared)
    scoring_rules.py        level/feedback, error types, break detection (no torch, shared)
    v2/
      phone_model.py        ONNX session -> log-posteriors
      ctc_align.py          numpy CTC forced alignment
      gop_features.py       GOP features, heard phones
      scorer.py             numpy phone MLP + word/utterance ridge
      analyser.py           audio + text -> V2Analysis
      pronunciation_v2_service.py   response assembly, gates, score curve
  utils/                    audio I/O, text normalisation
training/                   offline training and export (own CUDA venv, not imported by app/)
scripts/                    evaluation harness, sanity set, HF upload
debugs/                     benchmark and diagnostics
tests/                      pytest suite (+ synthetic sanity recordings)
```

Chi tiết từng tệp: [structure.md](structure.md). Luồng xử lý request v1 dạng văn bản: [workflow.md](workflow.md).
