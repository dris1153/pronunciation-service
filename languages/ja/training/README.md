<!-- doc-id: training-readme | lang: ja | source-rev: e36372fb -->

> 🌐 [`training/README.md`](../../../training/README.md)（rev `e36372fb`）の**日本語訳**です。英語版が正です。内容が異なる場合は英語版に従ってください。機械翻訳であり、ネイティブによる校閲は受けていません。

# training/ — オフラインのモデル学習（フェーズ B）

`app/` からは import されません。サービスの venv を CPU 専用に保つため、独自の CUDA venv を使います。

```bash
py -V:3.11 -m venv .venv-train
.venv-train/Scripts/python -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
.venv-train/Scripts/python -m pip install -r training/requirements-train.txt
```

## 音素 CTC モデル（HuBERT-base）

データ: LibriSpeech の `train-clean-100`、`dev-clean`、`test-clean`（openslr.org/12、CC BY 4.0）を `data/librispeech/` に展開したもの。
ラベル: 書き起こし → `g2p_en` → IPA、語彙 = サービスの 41 個の IPA 記号 + ブランク（`training/phone_labels.py`）。

```bash
.venv-train/Scripts/python -m training.train_phone_ctc --steps 25000      # best dev PER checkpoint → data/models/hubert-phone-ctc/
.venv-train/Scripts/python -m training.eval_per --split test-clean
```

入力の仕様（ランタイムと一致している必要があります）: 16 kHz モノラル float32、**ピーク正規化**、平均/分散の正規化なし。
ネイティブの音声のみを使います。正解ラベルが正規の発音になっている L2 音声では、決して学習しないでください（モデルが誤りを許容するようになってしまいます）。

サービス用にエクスポートします（FP32、動的な長さ、torch との一致を確認）:

```bash
.venv-train/Scripts/python -m training.export_onnx   # -> data/models/hubert-phone-ctc/model.onnx
```

## スコアラー（音素 MLP + リッジヘッド）

speechocean762 の train/test の特徴量が必要です（CC BY 4.0、中国語が母語 — フェーズ 03 のレポートにあるドメインギャップの注記も参照してください）:

```bash
python scripts/speechocean762_eval.py --api v2 --split train --out data/so762-v2-train.jsonl --report data/so762-v2-train-report.json
python scripts/speechocean762_eval.py --api v2 --split test  --out data/so762-v2-test.jsonl  --report data/so762-v2-test-report.json
.venv/Scripts/python -m training.train_scorer      # -> data/models/hubert-phone-ctc/scorer.json
```

`scorer.json` がなくても、ハーネスは音素ごとの特徴量を書き出します（スコアはゼロ）。学習に必要なのはそれだけです。
テスト分割は最終レポートにのみ使います。lambda と MDD のしきい値は、train の fold 外予測から得ます。
