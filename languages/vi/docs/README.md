<!-- doc-id: docs-readme | lang: vi | source-rev: c17acd89 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/README.md`](../../../docs/README.md) (rev `c17acd89`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Tài liệu

| Trang | Nội dung |
| --- | --- |
| [api.md](api.md) | Mọi endpoint, xác thực, lỗi, ví dụ request/response (v1 và v2) |
| [architecture.md](architecture.md) | Sơ đồ hệ thống, pipeline v1 so với v2, trình tự xử lý request v2, khởi động, cách tổ chức code |
| [scoring-v2.md](scoring-v2.md) | Cách pipeline thuần phoneme chấm điểm giọng nói, kết quả, giới hạn |
| [scoring-v1.md](scoring-v1.md) | Pipeline Wav2Vec2 gốc: công thức và ví dụ |
| [scoring-constants.md](scoring-constants.md) | Vì sao mỗi hằng số chấm điểm có giá trị như vậy (v1 và v2) |
| [evaluation.md](evaluation.md) | Chất lượng so với điểm chuyên gia, độ trễ, bộ nhớ, test, kế hoạch dữ liệu cho thêm các ngôn ngữ mẹ đẻ |
| [training.md](training.md) | Huấn luyện và export các model v2, công bố các tệp model |
| [configuration.md](configuration.md) | Tất cả biến môi trường |
| [deployment.md](deployment.md) | Docker, Railway, Coolify/nixpacks, các tệp model trên Hugging Face, định cỡ tài nguyên |
| [internal-integration.md](internal-integration.md) | Gọi dịch vụ từ backend: giới hạn tốc độ theo người dùng, wrapper, chuyển sang v2 |
| [workflow.md](workflow.md) | Luồng xử lý request dạng văn bản (v1), luồng xác thực, khởi động, luồng triển khai |
| [structure.md](structure.md) | Cấu trúc thư mục và ghi chú từng tệp |

Ngoài ra: tài liệu một trang song ngữ trong [`index.html`](../../../index.html) và nhật ký dự án trong [`journals/`](../../../docs/journals).

Các bản dịch (Tiếng Việt, 中文, 日本語, Español) nằm trong [`../languages/`](../../README.md); [STATUS.md](../../STATUS.md) cho biết bản nào đang khớp với các trang tiếng Anh này.
