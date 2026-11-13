<!-- doc-id: training-readme | lang: vi | source-rev: e36372fb -->

> 🌐 **Bản dịch tiếng Việt** của [`training/README.md`](../../../training/README.md) (rev `e36372fb`). Bản tiếng Anh là chuẩn: nếu hai bản khác nhau, hãy theo bản tiếng Anh. Bản dịch do máy thực hiện, chưa có người bản xứ rà soát.

# training/ — huấn luyện model offline (Phase B)

Không được `app/` import. Dùng venv CUDA riêng để venv của dịch vụ chỉ chạy CPU.

```bash
py -V:3.11 -m venv .venv-train
.venv-train/Scripts/python -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
.venv-train/Scripts/python -m pip install -r training/requirements-train.txt
```

## Model phoneme CTC (HuBERT-base)

Dữ liệu: LibriSpeech `train-clean-100`, `dev-clean`, `test-clean` (openslr.org/12, CC BY 4.0) giải nén vào `data/librispeech/`.
Nhãn: transcript → `g2p_en` → IPA, từ vựng = 41 ký hiệu IPA của dịch vụ + blank (`training/phone_labels.py`).

```bash
.venv-train/Scripts/python -m training.train_phone_ctc --steps 25000      # best dev PER checkpoint → data/models/hubert-phone-ctc/
.venv-train/Scripts/python -m training.eval_per --split test-clean
```

Hợp đồng đầu vào (phải khớp với runtime): 16 kHz mono float32, **chuẩn hóa đỉnh**, không chuẩn hóa mean/variance.
Chỉ dùng giọng bản xứ: không bao giờ huấn luyện trên audio L2 với nhãn chuẩn (model sẽ học cách bỏ qua lỗi).

Export cho dịch vụ (FP32, độ dài động, kiểm tra độ khớp với torch):

```bash
.venv-train/Scripts/python -m training.export_onnx   # -> data/models/hubert-phone-ctc/model.onnx
```

## Bộ chấm (MLP phone + các đầu ridge)

Cần các đặc trưng train/test của speechocean762 (CC BY 4.0, L1 tiếng Quan Thoại; xem thêm ghi chú về khoảng cách miền dữ liệu trong báo cáo Phase 03):

```bash
python scripts/speechocean762_eval.py --api v2 --split train --out data/so762-v2-train.jsonl --report data/so762-v2-train-report.json
python scripts/speechocean762_eval.py --api v2 --split test  --out data/so762-v2-test.jsonl  --report data/so762-v2-test-report.json
.venv/Scripts/python -m training.train_scorer      # -> data/models/hubert-phone-ctc/scorer.json
```

Không có `scorer.json`, harness vẫn ghi các đặc trưng theo từng phone (điểm số bằng 0), và đó là tất cả những gì huấn luyện cần.
Tập test chỉ dùng cho báo cáo cuối; các lambda và ngưỡng MDD lấy từ các dự đoán out-of-fold của tập train.
