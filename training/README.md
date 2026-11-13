<!-- doc-id: training-readme | rev: e36372fb -->
# training/ — offline model training (Phase B)

Not imported by `app/`. Uses its own CUDA venv so the service venv stays CPU-only.

```bash
py -V:3.11 -m venv .venv-train
.venv-train/Scripts/python -m pip install torch==2.5.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
.venv-train/Scripts/python -m pip install -r training/requirements-train.txt
```

## Phoneme CTC model (HuBERT-base)

Data: LibriSpeech `train-clean-100`, `dev-clean`, `test-clean` (openslr.org/12, CC BY 4.0) extracted to `data/librispeech/`.
Labels: transcript → `g2p_en` → IPA, vocabulary = the service's 41 IPA symbols + blank (`training/phone_labels.py`).

```bash
.venv-train/Scripts/python -m training.train_phone_ctc --steps 25000      # best dev PER checkpoint → data/models/hubert-phone-ctc/
.venv-train/Scripts/python -m training.eval_per --split test-clean
```

Input contract (must match the runtime): 16 kHz mono float32, **peak-normalised**, no mean/variance normalisation.
Native speech only — never train on L2 audio with canonical labels (the model would learn to forgive errors).

Export for the service (FP32, dynamic length, checks parity vs torch):

```bash
.venv-train/Scripts/python -m training.export_onnx   # -> data/models/hubert-phone-ctc/model.onnx
```

## Scorer (phone MLP + ridge heads)

Needs the speechocean762 train/test features (CC BY 4.0, Mandarin L1 — also see the domain-gap note in the Phase 03 report):

```bash
python scripts/speechocean762_eval.py --api v2 --split train --out data/so762-v2-train.jsonl --report data/so762-v2-train-report.json
python scripts/speechocean762_eval.py --api v2 --split test  --out data/so762-v2-test.jsonl  --report data/so762-v2-test-report.json
.venv/Scripts/python -m training.train_scorer      # -> data/models/hubert-phone-ctc/scorer.json
```

Without `scorer.json` the harness still writes the per-phone features (scores are zeros), which is all training needs.
The test split is only used for the final report; lambdas and the MDD threshold come from train out-of-fold predictions.
