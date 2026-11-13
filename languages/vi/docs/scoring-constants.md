<!-- doc-id: docs-scoring-constants | lang: vi | source-rev: 6006c067 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/scoring-constants.md`](../../../docs/scoring-constants.md) (rev `6006c067`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Lý do chọn các hằng số chấm điểm

Vì sao mỗi hằng số chấm điểm được gán cứng lại có giá trị như vậy. Thay đổi bất kỳ
hằng số nào trong số đó đều yêu cầu chạy bộ sanity:

```
python scripts/sanity_eval.py \
    --api-key=$API_KEY \
    --compare-baseline=tests/sanity_dataset/sanity_baseline.json
```

Nếu bộ so sánh báo độ lệch > 5 điểm hoặc có bất kỳ đảo bậc nào, hãy quyết định:

- **Hiệu chỉnh lại có chủ đích?** → cập nhật `sanity_baseline.json` và ghi lại
  thay đổi tại đây.
- **Hồi quy?** → hoàn tác.

---

## 1. Hiệu chỉnh GOP: `_FLOOR = -25.0`, `_CEIL = -3.0`

- **Ở đâu:** `app/services/gop_service.py` (bước chuẩn hóa)
- **Thực nghiệm:** log-prob CTC của các phoneme phát âm đúng nằm trong khoảng
  từ khoảng -25 (rất kém) đến -3 (xuất sắc). Ngay cả TTS hoàn hảo cũng hiếm khi vượt
  -3 vì khối lượng softmax được dàn trải trên toàn bộ từ vựng.
- **Rủi ro nếu đổi:** Ánh xạ tuyến tính → mọi điểm GOP dịch chuyển theo tỷ lệ,
  và điều này đi vào accuracy_score (trọng số 45%) và overall_score.

## 2. Điểm một phần cho phoneme tương tự: `0.3`

- **Ở đâu:** `app/services/pronunciation_service.py` — ma trận chi phí căn chỉnh
  phoneme.
- **Thực nghiệm:** Thay một phoneme bằng một phoneme cùng nhóm ngữ âm
  (ví dụ ɛ↔æ, đều là nguyên âm trước) được 0.3, so với 1.0 (khớp) hoặc 0.0 (khác
  nhóm). Giá trị cao hơn sẽ làm điểm độ chính xác cao hơn so với cách chấm chặt hơn của Azure; giá trị
  thấp hơn phạt quá nặng các biến thể giọng nhỏ.
- **Rủi ro nếu đổi:** Độ chính xác theo từng phoneme dịch chuyển → độ chính xác IPA
  tổng hợp dịch chuyển tuyến tính → accuracy_score (trọng số 55%) dịch chuyển.

## 3. Ngưỡng phát âm sai: `60.0`

- **Ở đâu:** `app/services/pronunciation_service.py` —
  `_MISPRONUNCIATION_THRESHOLD`.
- **Lý do:** Khớp với quy ước của Azure Speech SDK: các từ dưới 60%
  độ chính xác IPA bị gắn cờ là phát âm sai.
- **Rủi ro nếu đổi:** Việc phân loại `error_type` ở mức từ dịch chuyển; các từ
  mới bị xếp là phát âm sai không còn được tính vào
  `completeness_score`.

## 4. Hop size của Wav2Vec2: `320`

- **Ở đâu:** `app/services/pronunciation_service.py` — `_HOP_SIZE`.
- **Lý do:** Kiến trúc Wav2Vec2: frame 20 ms ở 16 kHz = 320 mẫu
  mỗi frame. Dùng cho căn chỉnh cưỡng bức thời gian từng từ, đi vào
  `fluency_score`.
- **Rủi ro nếu đổi:** Bất kỳ lần đổi model nào làm thay đổi hop cũng BẮT BUỘC
  phải cập nhật hằng số này; nếu không, thời gian từng từ sẽ sai → chỉ số
  độ trôi chảy trả về rác.
- **Chốt chặn CI:** Bộ sanity phát hiện sai lệch nếu model được nâng cấp mà không
  cập nhật hop.

## 5. Phạt tốc độ không nhất quán: `30 pts/wps` (ngữ điệu) so với `20 pts/wps` (độ trôi chảy)

- **Ở đâu:** `app/services/prosody_service.py` (~dòng 178) và
  `app/services/pronunciation_service.py` — `_RATE_PENALTY_PER_WPS`.
- **Trạng thái:** **Sự không nhất quán đã biết.** Lý do lịch sử của mức phạt
  bất đối xứng này không được ghi lại trong codebase. Được đánh dấu để hiệu chỉnh ở v2
  khi đã có dữ liệu production.
- **Rủi ro nếu thống nhất:** Cả hai điểm thành phần dịch chuyển → trọng số overall_score
  đổi → phải tạo lại baseline sanity.

---

## Hằng số v2 (`app/services/v2/`)

Các mục 1-5 là hằng số của v1. Pipeline v2 có hằng số riêng, phần lớn được học từ dữ liệu:

| Hằng số | Giá trị | Ở đâu | Vì sao |
| --- | --- | --- | --- |
| `SCORE_CURVE_EXPONENT` | `1.4` | `pronunciation_v2_service.py` | Ánh xạ các dự đoán trên thang chuyên gia (chủ yếu 6-10) sang thang chặt hơn của v1: `100 x (s/10)^1.4`. Với 1.3, `poor_001` còn 59.4, quá sát mốc 60. Được chỉnh trên 5 clip tổng hợp; cần hiệu chỉnh lại trên audio người học thật. Làm tương quan câu nói thay đổi <= 0.005 |
| `MIN_HEARD_RATIO` | `0.2` | `pronunciation_v2_service.py` | Nếu nghe thấy dưới 20% số phone kỳ vọng, audio được coi là không có tiếng nói (điểm 0). Tỷ lệ thấp nhất trong tiếng nói thật của speechocean762 là 0.31 |
| `mdd_threshold` | `1.48` (trên thang 2) | `scorer.json` | Điểm phone dưới mức này nghĩa là `is_correct_ipa = false`. Được chọn để tối đa hóa F1 phát hiện phát âm sai trên các dự đoán out-of-fold của tập train |
| `MIN_SAMPLES` | `400` | `phone_model.py` | Phần conv đầu vào của HuBERT từ chối audio ngắn hơn (25 ms) |
| `Z_CLIP` | `10` | `scorer.py` | One-hot của các phone hiếm có phương sai rất nhỏ; z-score không cắt đạt ~200 và làm hỏng việc fit |
| Ngưỡng từ phát âm sai | `60` | `scoring_rules.py` | Dùng chung với v1 (Azure dùng cùng ngưỡng) |
| Ngưỡng quãng ngắt | `0.8 s` / `0.15 s` | `scoring_rules.py` | Dùng chung với v1; v2 áp dụng chúng lên các khoảng từ đã căn chỉnh |

Đổi model phone, bố cục đặc trưng hoặc bộ phone đều yêu cầu huấn luyện lại `scorer.json` ([training.md](training.md)). Chất lượng được kiểm tra bằng `scripts/speechocean762_eval.py --api v2` ([evaluation.md](evaluation.md)).

## Cách cập nhật một hằng số an toàn

1. Thực hiện thay đổi trong tệp service liên quan.
2. Khởi động lại server local.
3. Chạy:
   ```
   python scripts/sanity_eval.py \
       --api-key=$API_KEY \
       --compare-baseline=tests/sanity_dataset/sanity_baseline.json
   ```
4. Nếu exit code 0: thay đổi nằm trong dung sai. Commit kèm một mục trong
   changelog bên dưới.
5. Nếu exit code 1 do hiệu chỉnh lại có chủ đích: tạo lại baseline, commit
   cả hai tệp, ghi lại việc hiệu chỉnh tại đây.
6. Nếu exit code 1 do hồi quy ngoài ý muốn: hoàn tác.

## Changelog

- _2026-05-04_ — Tài liệu ban đầu (Phase 06).
