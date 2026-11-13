<!-- doc-id: docs-scoring-v1 | lang: vi | source-rev: f3f95227 -->

> 🌐 **Bản dịch tiếng Việt** của [`docs/scoring-v1.md`](../../../docs/scoring-v1.md) (rev `f3f95227`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# Chấm điểm v1 (pipeline Wav2Vec2 ASR)

Cách `POST /api/v1/evaluate` tạo ra điểm số: ASR mức từ, tham chiếu IPA từ g2p, GOP dựa trên hậu nghiệm CTC, ngữ điệu theo cao độ và các điểm thành phần kiểu Azure.
Pipeline này không thay đổi. Pipeline mức phoneme mới hơn được mô tả trong [scoring-v2.md](scoring-v2.md); các hằng số và lý do chọn chúng nằm trong [scoring-constants.md](scoring-constants.md).

Các điểm yếu đã đo của v1 trên speechocean762 (người lớn): GOP mức phone tương quan 0.03 với điểm chuyên gia, ngữ điệu 0.11, và phát hiện phát âm sai kiểu nghe-được-so-với-kỳ-vọng có F1 0.27 (precision 0.16). Hầu hết các lỗi lớn đều bắt nguồn từ việc ASR sinh ra văn bản vô nghĩa trên giọng có accent. Xem [evaluation.md](evaluation.md).

## Pipeline

### Tổng quan pipeline

```
Audio bytes → ASR (Wav2Vec2) → Transcription → IPA comparison + GOP scoring → Unified response
```

1. **Xử lý audio**: nạp và resample audio về 16 kHz mono float32 (librosa)
2. **Phiên âm ASR**: Wav2Vec2 phiên âm những gì thực sự đã được nói
3. **Chuyển đổi IPA**: cả văn bản tham chiếu và bản phiên âm → phoneme IPA (g2p_en + ánh xạ ARPAbet→IPA)
4. **So sánh IPA**: DP căn chỉnh riêng cho từ (`_align_words`) và phoneme (`_align_phonemes`) với dung sai ε khi lần ngược
5. **Chấm GOP**: log hậu nghiệm CTC với cách chia frame có xét phần dư (không bỏ rơi frame ở đuôi)
6. **Phân tích ngữ điệu**: trích xuất cao độ bằng librosa pyin, chấm điểm theo phương sai/khoảng/đường nét cao độ, phát hiện giọng đều đều
7. **Phân loại lỗi**: mỗi từ nhận một `ErrorType`: `None`, `Mispronunciation`, `Omission`, `Insertion`, `UnexpectedBreak` hoặc `MissingBreak`
8. **Điểm thành phần**: `accuracy_score` = 55% IPA + 45% GOP; `completeness_score` = tỷ lệ các từ tham chiếu phát âm đúng có trọng số theo độ chính xác; `fluency_score` = tốc độ nói + phân tích quãng ngắt; `prosody_score` = ngữ điệu + tốc độ + nhịp điệu
9. **Điểm kết hợp**: công thức có trọng số kiểu Azure: sắp xếp 4 điểm thành phần từ thấp→cao, `0.4 × s0 + 0.2 × s1 + 0.2 × s2 + 0.2 × s3`

### Công thức chấm điểm

#### Điểm độ chính xác (điểm thành phần)

Kết hợp so sánh IPA mức phoneme và chấm GOP:

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

#### Điểm độ đầy đủ (điểm thành phần)

Đo số từ tham chiếu được người nói phát âm **đúng**:

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

Một từ được coi là "phát âm đúng" nếu:

1. Phép căn chỉnh là `match` hoặc `substitute` (từ đã được thử đọc), **và**
2. Độ chính xác IPA mức từ ≥ 60% (`_MISPRONUNCIATION_THRESHOLD`)

Các từ bị bỏ sót (`delete`) và các từ phát âm sai (độ chính xác < 60%) không được tính. Các từ nói thừa (`insert`) không ảnh hưởng đến độ đầy đủ.

#### Điểm độ trôi chảy (điểm thành phần)

Đo độ trôi chảy của lời nói bằng thời gian frame CTC mức từ từ căn chỉnh cưỡng bức GOP:

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

**Tốc độ nói**: độ lệch so với tốc độ lý tưởng (~3.0 từ/giây). Tốc độ trong dải dung sai ±0.5 wps được điểm tối đa; độ lệch vượt quá bị phạt 20 điểm cho mỗi wps.

**Phạt quãng ngắt**: các khoảng trống dài (>0.8s) giữa hai từ liên tiếp làm giảm độ trôi chảy, mô phỏng sự ngập ngừng và ngắt quãng bất ngờ. Mỗi giây ngắt dư tốn 15 điểm.

Azure định nghĩa độ trôi chảy là "mức độ lời nói khớp với cách người bản xứ dùng các quãng im lặng giữa các từ": mẫu quãng ngắt là tín hiệu chính (60%), tốc độ nói là chỉ báo phụ (40%).

#### Điểm ngữ điệu (điểm thành phần)

Đánh giá sự biến thiên cao độ, tốc độ nói và độ tự nhiên của nhịp điệu. Điểm ngữ điệu có ba thành phần:

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

**Điểm ngữ điệu lên xuống (55%)**: kết hợp ba chỉ số cao độ:

```math
IntonationScore = 0.50 \times VarianceScore + 0.30 \times RangeScore + 0.20 \times ContourScore
```

- _Điểm phương sai_: hệ số biến thiên của cao độ (CV = std/mean). CV ≤ `monotone_threshold` (0.08) = 0 điểm; CV ≥ `cv_upper` (0.25) = 100 điểm. Nội suy tuyến tính ở giữa.
- _Điểm khoảng_: khoảng cao độ tính bằng nửa cung (semitone). 0 st = 0 điểm; ≥ 15 st = 100 điểm. Nội suy tuyến tính.
- _Điểm đường nét_: tỷ lệ đổi hướng của đường nét cao độ. Tỷ lệ mục tiêu 0.45 được điểm tối đa; độ lệch bị phạt tuyến tính.

**Điểm tốc độ (20%)**: độ lệch của số từ mỗi giây so với 3.0 wps lý tưởng (dung sai ±0.5). Mỗi 1 wps vượt dung sai → −30 điểm.

**Điểm nhịp điệu (25%)**: Pairwise Variability Index chuẩn hóa (nPVI). Đo độ tự nhiên của nhịp theo trọng âm; tiếng Anh bản xứ nPVI ~50–70, ngôn ngữ nhịp theo âm tiết ~30–40. Chấm tuyến tính: nPVI ≤30 → 0, nPVI ≥70 → 100.

**Phát hiện giọng đều đều**: khi CV của cao độ < ngưỡng (0.08), `is_monotone = True` và điểm ngữ điệu bị chặn trần ở 30.

**Chốt chặn tỷ lệ có thanh**: nếu dưới 10% số frame có thanh, trả về điểm 0 (tín hiệu có thanh không đủ).

**Hành vi mặc định**: khi không có thời lượng từ (không có thời gian CTC), tốc độ và nhịp điệu mặc định là 50 (trung tính).

#### Điểm tổng kết hợp

Các điểm thành phần được sắp xếp từ thấp→cao và kết hợp bằng công thức PronScore của Azure:

```math
CombinedScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3
```

Điểm thành phần thấp nhất có trọng số lớn nhất (40%), phạt nặng chiều yếu nhất.

#### Phân loại lỗi mức từ

Mỗi từ trong kết quả nhận một `error_type` dựa trên căn chỉnh và độ chính xác:

| Điều kiện                                       | ErrorType          |
| ----------------------------------------------- | ------------------ |
| Từ được căn chỉnh (match/substitute), độ chính xác ≥ 60% | `None`             |
| Từ được căn chỉnh (match/substitute), độ chính xác < 60% | `Mispronunciation` |
| Từ có trong tham chiếu nhưng không được nói     | `Omission`         |
| Từ được nói nhưng không có trong tham chiếu     | `Insertion`        |
| Phát hiện quãng ngắt dài (>0.8s) trước từ       | `UnexpectedBreak`  |
| Thiếu quãng ngắt ở ranh giới dấu câu (<0.15s)   | `MissingBreak`     |

Ngưỡng: `60.0` (khớp với Azure Speech SDK).

#### Độ chính xác IPA (trọng số: 55%)

Văn bản tham chiếu và văn bản phiên âm được so sánh ở **hai mức** bằng căn chỉnh chuỗi dựa trên Levenshtein (quy hoạch động với độ chính xác `float64` và dung sai lần ngược ε = 10⁻⁶):

**Mức 1: Căn chỉnh từ (`_align_words`):**

Danh sách từ tham chiếu và từ phiên âm được căn chỉnh bằng DP Levenshtein thuần (không có chi phí tương đồng ngữ âm: việc hai từ bằng nhau là nhị phân). Cho ra các phép match / substitute / insert / delete. Các từ thừa do người dùng nói (insertion) bị phạt trong điểm tổng.

**Mức 2: Căn chỉnh phoneme (`_align_phonemes`, theo từng cặp từ):**

Với mỗi cặp từ đã căn chỉnh, chuỗi phoneme tham chiếu và phoneme thực tế được căn chỉnh bằng cùng thuật toán DP. Khoảng cách chỉnh sửa dùng **tương đồng ngữ âm**: thay một phoneme bằng một phoneme cùng nhóm ngữ âm (ví dụ `ɛ` ↔ `æ`, đều là nguyên âm trước) tốn ít hơn so với thay bằng phoneme thuộc nhóm khác.

```
Reference IPA:   [h, ɛ, l, oʊ]
Actual IPA:      [h, ɛ, ə, l, oʊ]
Alignment:
  h  = h    ✓  match
  ɛ  = ɛ    ✓  match
  -  ← ə    ✗  insert (extra phoneme in actual)
  l  = l    ✓  match
  oʊ = oʊ   ✓  match
→ 4/4 correct ref phonemes = 100% (insertion penalised in overall score)
```

**Chấm độ tin cậy của phoneme:**

| Kết quả căn chỉnh                       | Độ tin cậy |
| --------------------------------------- | ---------- |
| Khớp chính xác                          | `1.0`      |
| Thay thế (cùng nhóm ngữ âm)             | `0.3`      |
| Thay thế (khác nhóm ngữ âm)             | `0.0`      |
| Xóa (thiếu trong thực tế)               | `0.0`      |
| Chèn (thừa trong thực tế)               | `0.0`      |

**Độ chính xác theo từng từ:**

```math
WordAccuracy = \frac{CorrectPhonemes}{RefPhonemesInWord} \times 100
```

**Độ chính xác IPA tổng (có phạt chèn thêm):**

```math
OverallIPA = \frac{\sum CorrectPhonemes}{\sum RefPhonemes + \sum InsertedPhonemes} \times 100
```

> Các từ nói thừa cộng số phoneme của chúng vào mẫu số, làm giảm độ chính xác tổng.

#### Điểm GOP (trọng số: 45%)

GOP (Goodness of Pronunciation) dùng log hậu nghiệm CTC từ Wav2Vec2:

**Bước 1: Log hậu nghiệm CTC:**

Audio → Wav2Vec2 → logit đầu ra → `log_softmax` → ma trận `(T, V)` với T = số frame, V = kích thước từ vựng

**Bước 2: Chia frame có xét phần dư:**

Chia T frame cho N phoneme. Mỗi phoneme nhận một phần cơ sở, với các frame dư được phân cho các phoneme **cuối**:

```math
base = \lfloor T / N \rfloor,\quad remainder = T \bmod N
```

Các phoneme ở vị trí `[N - remainder, N)` nhận `base + 1` frame; các phoneme đứng trước nhận `base` frame. Cách này đảm bảo **dùng hết cả T frame**, không frame đuôi nào bị bỏ.

**Bước 3: GOP thô theo từng phoneme:**

Với mỗi phoneme `p`, ánh xạ sang token từ vựng của Wav2Vec2 qua `_IPA_TO_WAV2VEC`, rồi tính log xác suất trung bình trên các frame được gán `[start, end)`:

```math
GOP_{raw}(p) = \frac{1}{d} \sum_{t=start}^{end-1} \log P(p \mid o_t)
```

trong đó `d = end - start` là số frame được gán cho phoneme `p`.

> Nếu phoneme không có trong từ vựng → phương án dự phòng: dùng log xác suất lớn nhất trên toàn từ vựng cho các frame đó.

**Bước 4: Chuẩn hóa về [0, 100]:**

Hiệu chỉnh theo thực nghiệm: log-prob CTC của các phoneme phát âm đúng thường nằm trong khoảng từ −25 (rất kém) đến −3 (xuất sắc). Ngay cả audio TTS "hoàn hảo" cũng hiếm khi cho điểm thô trên −3 vì softmax của CTC luôn dàn khối lượng xác suất trên toàn bộ từ vựng.

```math
GOP_{norm} = \frac{\text{clamp}(GOP_{raw},\ -25,\ -3) - (-25)}{22} \times 100
```

Được cắt về `[0, 100]`.

**Bước 5: Tổng hợp:**

- **GOP theo từ** = trung bình điểm GOP của các phoneme trong từ đó
- **GOP tổng** = trung bình điểm GOP của mọi phoneme

> Ranh giới từ dùng theo dõi dựa trên chỉ số (không dùng so sánh chuỗi), nên các từ trùng lặp như "the cat and the dog" được xử lý đúng.

#### Điểm kết hợp

```math
AccuracyScore = IPA_{accuracy} \times 0.55 + GOP_{score} \times 0.45
```

```math
CompletenessScore = \frac{CorrectlyPronouncedWords}{ReferenceWords} \times 100
```

```math
FluencyScore = 0.4 \times RateScore + 0.6 \times PauseScore
```

```math
ProsodyScore = 0.55 \times IntonationScore + 0.20 \times SpeedScore + 0.25 \times RhythmScore
```

```math
OverallScore = 0.4 \times S_0 + 0.2 \times S_1 + 0.2 \times S_2 + 0.2 \times S_3 \quad (S_0 \leq S_1 \leq S_2 \leq S_3)
```

#### Mức chất lượng

| Khoảng điểm  | Mức          | Nhận xét                             |
| ------------ | ------------ | ------------------------------------ |
| **80 – 100** | 🟢 Excellent | Lời nói khớp sát với tham chiếu      |
| **60 – 79**  | 🔵 Good      | Có thể cải thiện thêm đôi chút       |
| **40 – 59**  | 🟡 Fair      | Một số âm cần luyện tập              |
| **0 – 39**   | 🔴 Poor      | Cần cải thiện đáng kể                |

### Ví dụ chấm điểm

```
Reference:     "the cat and the dog"
Transcription: "the cat an the dock"

Word alignment (DP):
  the  = the   ✓ match     → ErrorType: None
  cat  = cat   ✓ match     → ErrorType: None
  and  ≈ an    ~ substitute → ErrorType: depends on accuracy
  the  = the   ✓ match     → ErrorType: None
  dog  ≈ dock  ~ substitute → ErrorType: depends on accuracy

Phoneme alignment for "and" → "an":
  Reference: [æ, n, d]    Actual: [æ, n]
  æ = æ  ✓ match     confidence=1.0
  n = n  ✓ match     confidence=1.0
  d → ∅  ✗ delete    confidence=0.0
  → Word accuracy = 2/3 × 100 = 66.7%  → ErrorType: None (≥60%)

Phoneme alignment for "dog" → "dock":
  Reference: [d, ɑ, ɡ]    Actual: [d, ɑ, k]
  d = d  ✓ match     confidence=1.0
  ɑ = ɑ  ✓ match     confidence=1.0
  ɡ ≈ k  ✗ substitute (same group: voiced/voiceless plosive) confidence=0.3
  → Word accuracy = 2/3 × 100 = 66.7%  → ErrorType: None (≥60%)

Overall IPA = (3+3+2+3+2) / (3+3+3+3+3) = 13/15 × 100 = 86.7%

GOP Scoring: (per-phoneme CTC log-prob scores, normalised 0-100)
  → Overall GOP = 72.5 (example)

Sub-scores:
  Accuracy    = 86.7 × 0.55 + 72.5 × 0.45 = 47.7 + 32.6 = 80.3
  Completeness = 5/5 × 100 = 100.0  (all reference words attempted)
  Fluency      = 95.0  (normal speech rate, no long pauses)
  Prosody      = 78.0  (good pitch variation, not monotone)

Overall = sorted([80.3, 100.0, 95.0, 78.0]) = [78.0, 80.3, 95.0, 100.0]
        = 0.4 × 78.0 + 0.2 × 80.3 + 0.2 × 95.0 + 0.2 × 100.0
        = 31.2 + 16.06 + 19.0 + 20.0 = 86.3
Level = EXCELLENT ✔
```

