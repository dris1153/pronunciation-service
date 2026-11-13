<!-- doc-id: docs-configuration | lang: vi | source-rev: e26350fb -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/configuration.md`](../../../docs/configuration.md) (rev `e26350fb`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Cấu hình

Mọi thiết lập đều là biến môi trường (hoặc mục trong `.env`, được tìm từ thư mục gốc của dự án). Tên không phân biệt hoa thường. Mẫu là [`.env.example`](../../../.env.example); nguồn chuẩn là [`app/core/config.py`](../../../app/core/config.py).

> `.env` chỉ chấp nhận các tên dưới đây. Một khóa lạ (gõ sai, hoặc các giá trị chỉ dùng lúc build như `V2_MODEL_REPO`) sẽ làm quá trình khởi động thất bại với `extra_forbidden`. Hãy đặt các giá trị chỉ dùng lúc build trong môi trường build, không đặt trong `.env`.

## Ứng dụng

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `APP_NAME` | `Pronunciation Validator` | Hiển thị trong OpenAPI và `model-info` |
| `APP_VERSION` | `1.0.0` | Hiển thị trong OpenAPI, `/health`, `model-info` |
| `APP_HOST` | `0.0.0.0` | Địa chỉ bind |
| `PORT` | `8000` | Cổng server (Railway tự gán lúc chạy) |
| `DEBUG` | `false` | `true` bỏ qua kiểm tra độ mạnh của API key và dùng log dễ đọc cho người. Luôn để `false` ở production |
| `LOG_LEVEL` | `INFO` | Mức log. `DEBUG=false` ghi mỗi bản ghi thành một dòng JSON |

## Model v1 (Wav2Vec2)

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `ASR_MODEL_NAME` | `facebook/wav2vec2-base-960h` | Model id trên Hugging Face. `...-large-960h-lv60-self` chính xác hơn với giọng vùng miền nhưng nặng ~1.2 GB và ~7 s mỗi clip |
| `ASR_MODEL_CACHE_DIR` | `./model_cache` | Thư mục cache model |
| `DEVICE` | `cpu` | `cpu` hoặc `cuda` |
| `INFERENCE_BACKEND` | `torch_fp32` | `torch_fp32` hoặc `torch_int8` (INT8 động cho ASR v1) |

## Model phone v2

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `PHONE_MODEL_DIR` | `./data/models/hubert-phone-ctc` | Thư mục chứa `model.int8.onnx` (và tùy chọn `model.onnx`), `vocab.json`, `scorer.json` |
| `PHONE_MODEL_INT8` | `true` | `true` tải `model.int8.onnx` (~116 MB, nhanh hơn ~3x); `false` tải `model.onnx` (FP32, ~360 MB) |

Tệp thiếu hoặc không đọc được khiến `/api/v2/evaluate` trả về `503`; v1 không bị ảnh hưởng. Cách đưa các tệp vào một image: [deployment.md](deployment.md).

## Audio

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `AUDIO_SAMPLE_RATE` | `16000` | Tần số lấy mẫu của model (Hz). Cả hai pipeline đều giả định 16 kHz |
| `AUDIO_MAX_DURATION_SEC` | `30` | Audio dài hơn bị từ chối với `400` |

Giới hạn kích thước tải lên (10 MB) và các MIME type được chấp nhận là hằng số trong `app/core/constants.py`.

## Bảo mật

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `API_KEY` | _(trống)_ | `X-API-Key` cho các endpoint được bảo vệ. Bắt buộc khi `DEBUG=false`: ít nhất 32 ký tự và không nằm trong danh sách khóa yếu. Tạo khóa: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SERVICE_API_KEY` | _(trống)_ | Bật giới hạn tốc độ theo từng người dùng cuối cho một backend đáng tin cậy (`X-Service-Auth`). Xem [internal-integration.md](internal-integration.md) |
| `TRUSTED_PROXY_CIDRS_STR` | `172.16.0.0/12,10.0.0.0/8,192.168.0.0/16` | Các peer mà `X-Forwarded-For` của chúng được tin cậy. Hãy thu hẹp về proxy của bạn |
| `CORS_ORIGINS_STR` | `*` | Danh sách origin cách nhau bằng dấu phẩy (hoặc một mảng JSON). `*` chỉ dùng cho phát triển |

## Giới hạn tốc độ, timeout, đồng thời

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `RATE_LIMIT_ENABLED` | `true` | Công tắc tổng (tắt trong test và CI) |
| `RATE_LIMIT_EVALUATE_PER_MINUTE` | `20` | Giới hạn cho mỗi route `/api/v1/evaluate` và `/api/v2/evaluate` (mỗi route giữ bộ đếm riêng) |
| `RATE_LIMIT_TRANSCRIBE_PER_MINUTE` | `15` | |
| `RATE_LIMIT_TEXT_ANALYSIS_PER_MINUTE` | `120` | |
| `REQUEST_TIMEOUT_SEC` | `90` | Request kéo dài hơn trả về `504` |
| `MAX_CONCURRENT_INFERENCES` | `0` | Số slot suy luận. `0` = tự động (số core - 1, tối đa 4). Số thread mỗi slot = số core / số slot. Đo thực tế: 4 vCPU -> `2`; 2 vCPU -> tự động (1 slot) |
| `INFERENCE_QUEUE_TIMEOUT_SEC` | `60` | Thời gian một request được chờ slot trước khi nhận `503` kèm `Retry-After` |

Dưới Docker `--cpus` hoặc Railway, hạn mức CPU không hiện ra với bước dò affinity; hãy đặt `OMP_NUM_THREADS` bằng số vCPU và nó sẽ được ưu tiên hơn giá trị tự tính.

## Ngữ điệu (chỉ v1)

| Biến | Mặc định | Mô tả |
| --- | --- | --- |
| `PROSODY_PITCH_MIN_HZ` / `PROSODY_PITCH_MAX_HZ` | `65` / `600` | Khoảng tìm kiếm của pyin |
| `PROSODY_MONOTONE_THRESHOLD` | `0.08` | Hệ số biến thiên của cao độ thấp hơn mức này được coi là giọng đều đều |
| `PROSODY_PITCH_CV_UPPER` | `0.25` | CV bằng hoặc cao hơn mức này được 100 điểm. Phải lớn hơn ngưỡng giọng đều đều |

## Chỉ dùng lúc build (không đọc từ `.env`)

| Tên | Ở đâu | Mô tả |
| --- | --- | --- |
| `V2_MODEL_REPO` | Build arg của Docker / build variable của nixpacks | Repo Hugging Face riêng tư chứa các tệp v2, ví dụ `dris1153/pronunciation-v2` |
| `HF_TOKEN` | Build secret của Docker (`--secret id=hf_token,env=HF_TOKEN`) / build variable của nixpacks | Token đọc cho repo đó. Không bao giờ commit hoặc nhúng vào một layer của image |
| `ASR_MODEL_NAME` | Build arg của Docker | Ghi đè model v1 được đóng sẵn trong image |
