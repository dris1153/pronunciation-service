<!-- doc-id: training-readme | lang: zh | source-rev: e36372fb -->

> 🌐 **中文翻译**，源文件 [`training/README.md`](../../../training/README.md)（rev `e36372fb`）。以英文版为准：若两者不一致，请以英文版为准。本译文由机器翻译，尚未经母语者审校。

# training/ — 离线模型训练（Phase B）

不会被 `app/` 导入。使用自己的 CUDA 虚拟环境，因此服务的虚拟环境保持仅用 CPU。

```bash
py -V:3.11 -m venv .venv-train
.venv-train/Scripts/python -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
.venv-train/Scripts/python -m pip install -r training/requirements-train.txt
```

## 音素 CTC 模型（HuBERT-base）

数据：LibriSpeech `train-clean-100`、`dev-clean`、`test-clean`（openslr.org/12，CC BY 4.0），解压到 `data/librispeech/`。
标签：转写文本 → `g2p_en` → IPA，词表 = 服务使用的 41 个 IPA 符号 + blank（`training/phone_labels.py`）。

```bash
.venv-train/Scripts/python -m training.train_phone_ctc --steps 25000      # best dev PER checkpoint → data/models/hubert-phone-ctc/
.venv-train/Scripts/python -m training.eval_per --split test-clean
```

输入约定（必须与运行时一致）：16 kHz 单声道 float32，**峰值归一化**，不做均值/方差归一化。
只使用母语者语音 —— 切勿在带规范标签的 L2 音频上训练（模型会学会原谅错误）。

导出供服务使用（FP32，动态长度，检查与 torch 的一致性）：

```bash
.venv-train/Scripts/python -m training.export_onnx   # -> data/models/hubert-phone-ctc/model.onnx
```

## 评分器（音素 MLP + 岭回归头）

需要 speechocean762 的 train/test 特征（CC BY 4.0，母语为普通话 —— 另见 Phase 03 报告中关于领域差异的说明）：

```bash
python scripts/speechocean762_eval.py --api v2 --split train --out data/so762-v2-train.jsonl --report data/so762-v2-train-report.json
python scripts/speechocean762_eval.py --api v2 --split test  --out data/so762-v2-test.jsonl  --report data/so762-v2-test-report.json
.venv/Scripts/python -m training.train_scorer      # -> data/models/hubert-phone-ctc/scorer.json
```

没有 `scorer.json` 时，评测脚本仍会写出逐音素特征（评分为零），这正是训练所需要的全部。
测试集仅用于最终报告；lambda 和 MDD 阈值来自训练集的 out-of-fold 预测。
