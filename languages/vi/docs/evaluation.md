<!-- doc-id: docs-evaluation | lang: vi | source-rev: e6f94b86 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/evaluation.md`](../../../docs/evaluation.md) (rev `e6f94b86`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Đánh giá, benchmark và test

## Chất lượng so với điểm chuyên gia

[speechocean762](https://www.openslr.org/101/) (CC BY 4.0; Zhang et al., Interspeech 2021): 5000 câu nói từ 250 người nói không bản xứ (L1 là tiếng Quan Thoại, một nửa là trẻ em), được 5 chuyên gia chấm ở mức phone (0-2), từ (0-10) và câu nói (0-10). Giải nén vào `data/speechocean762/`. Bộ harness chạy pipeline ngay trong tiến trình (không qua HTTP, không giới hạn tốc độ) và tiếp tục từ tệp JSONL đầu ra của nó.

```bash
python scripts/speechocean762_eval.py --api v1 --out data/so762-v1-test.jsonl --report data/so762-v1-test-report.json
python scripts/speechocean762_eval.py --api v2 --out data/so762-v2-test.jsonl --report data/so762-v2-test-report.json
python scripts/speechocean762_v2_signal.py data/so762-v2-test.jsonl     # phone correlation, MDD, confusions, latency
```

Nó báo cáo tương quan Pearson cho điểm câu nói, từ và phone, cùng precision / recall / F1 của phát hiện phát âm sai (MDD), cho tất cả người nói và chỉ riêng người lớn (18+). "Phát âm sai" nghĩa là điểm phone của chuyên gia dưới 1.0 (khoảng 4% số phone).

| Tập test | v1 người lớn | v2 người lớn | v2 tất cả |
| --- | --- | --- | --- |
| Câu nói tổng / độ chính xác | 0.619 / 0.669 | 0.852 / 0.829 | 0.779 / 0.749 |
| Câu nói độ trôi chảy / ngữ điệu | 0.630 / 0.108 | 0.876 / 0.853 | 0.817 / 0.796 |
| Độ chính xác của từ | 0.020 | 0.643 | 0.591 |
| Độ chính xác của phone | 0.033 | 0.630 | 0.590 |
| MDD F1 | 0.269 | 0.537 | 0.480 |

Ghi chú: số liệu v2 dùng model FP32; INT8 lệch không quá 0.004 trên mọi chỉ số (độ đầy đủ, một điểm theo quy tắc gần như không có phương sai trong nhãn, lệch 0.010). Đường cong điểm làm tương quan câu nói thay đổi không quá 0.005. Các lỗi lớn nhất của v1 đến từ việc ASR sinh ra văn bản vô nghĩa với giọng có accent. Cách v2 hoạt động: [scoring-v2.md](scoring-v2.md).

### Những điều số liệu này không cho bạn biết

- **Mọi người nói đều có L1 là tiếng Quan Thoại.** Người học Việt Nam mắc các lỗi khác (phụ âm cuối, th/dh, s/sh, cụm phụ âm). Chưa có số liệu nào cho L1 tiếng Việt.
- Các clip sanity đứng sau số mũ của đường cong điểm là năm bản ghi tổng hợp (gTTS).
- Bộ chấm chưa được kiểm chứng trên audio dài từ 20 đến 30 s.

### Kế hoạch dữ liệu cho người học tiếng Việt

Một đợt khảo sát cho thấy **không có kho dữ liệu tiếng Anh nào có L1 tiếng Việt, mở và dùng được cho mục đích thương mại, kèm điểm phát âm**. L2-ARCTIC có bốn người nói tiếng Việt nhưng nhãn phone chỉ ở dạng nhị phân và giấy phép phi thương mại; speechocean762 chỉ có tiếng Quan Thoại; các kho giọng bản xứ tiếng Việt không chứa tiếng Anh. Hướng thực tế là ghi âm và gán nhãn người học theo giao thức của speechocean762 (3+ người chấm, phone 0-2 / từ / câu nói), bắt đầu với khoảng 50-100 người nói là người lớn và 500-1000 câu nói để hiệu chỉnh lại bộ chấm.

## Độ trễ và bộ nhớ

`debugs/benchmark.py` đo thời gian của pipeline thật ngay trong tiến trình. `--cpus N` ghim tiến trình vào N core để mô phỏng một máy chủ N vCPU.

```bash
python debugs/benchmark.py --api v1 --cpus 4
python debugs/benchmark.py --api v2 --int8 --cpus 4 --concurrency 2
```

Đo trên một máy dev Windows (28 core logic), các clip sanity gTTS dài 1.2-4.2 s, p50 tính bằng ms:

| Clip 3.4 s | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 2 vCPU | 610 | 375 | **240** |
| 4 vCPU | 381 | 201 | **125** |

| Đồng thời (2 slot, 30 request) | v1 | v2 FP32 | **v2 INT8** |
| --- | --- | --- | --- |
| 4 vCPU, p50 / p90 ms | 461 / 891 | 155 / 416 | **93 / 271** |
| 4 vCPU, req/s | 3.9 | 8.2 | **13.2** |
| 2 vCPU, req/s | 2.7 | 4.5 | **7.4** |

| Bộ nhớ (RSS) | sau khi tải | sau các request |
| --- | --- | --- |
| v1 | 796 MB | 970-1090 MB |
| v2 FP32 | 928 MB | 1050-1170 MB |
| v2 INT8 | **430 MB** | 600-660 MB |
| v1 + v2 INT8 trong một tiến trình | 1030 MB | chưa đo |

Ở v2, model gần như là toàn bộ chi phí (INT8, 4 vCPU, clip 3.4 s: ONNX ~120 ms, căn chỉnh ~3 ms, bộ chấm ~1 ms). INT8 là mặc định và là lựa chọn hợp lý duy nhất trên các máy chủ nhỏ; FP32 nặng hơn v1 lúc tải. Đây là số liệu trên máy dev: hãy chạy lại benchmark trên máy chủ thật trước khi chuyển client, vì mức tăng tốc của INT8 phụ thuộc vào tập lệnh CPU hỗ trợ. Mỗi `/evaluate` cũng ghi log một bản ghi `evaluate_timing` với số mili giây của từng giai đoạn.

## Test

```bash
pytest tests/ -v
```

Khoảng 460 test: API (v1 và v2), xác thực và giới hạn tốc độ, xử lý audio, các service văn bản/IPA/GOP/ngữ điệu, căn chỉnh và quy tắc chấm điểm, căn chỉnh CTC của v2 (khớp với `torchaudio.forced_align`), đặc trưng, bộ chấm, và một chốt chặn đảm bảo `app/services/v2/` không bao giờ import torch. Các test cần tệp model v2 thật (dải điểm sanity, cổng chặn nhiễu) sẽ tự bỏ qua khi thiếu tệp. `asyncio_mode = "auto"`.

`tests/sanity_dataset/` chứa năm bản ghi tổng hợp (3 tốt, 2 kém) kèm dải điểm kỳ vọng; tạo lại chúng bằng `scripts/generate_sanity_audio.py`.

**Vấn đề đã biết:** hai trường hợp sanity của v1 (`poor_001`, `poor_002`) thất bại vì v1 chấm các clip đó cao hơn trần 60 của dải một chút. v2 đạt cả hai.
