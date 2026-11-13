"""Export the phone CTC checkpoint to ONNX FP32 (dynamic time axis).

    python -m training.export_onnx --model data/models/hubert-phone-ctc

Writes model.onnx next to the checkpoint. vocab.json is already there.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
from transformers import HubertForCTC

ROOT = Path(__file__).resolve().parent.parent


class _Logits(torch.nn.Module):
    def __init__(self, model: HubertForCTC) -> None:
        super().__init__()
        self.model = model

    def forward(self, wave: torch.Tensor) -> torch.Tensor:
        return self.model(wave).logits


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=Path, default=ROOT / "data" / "models" / "hubert-phone-ctc")
    p.add_argument("--opset", type=int, default=17)
    args = p.parse_args()

    model = HubertForCTC.from_pretrained(args.model).eval()
    wrapped = _Logits(model).eval()
    dummy = torch.randn(1, 16000 * 3)
    out = args.model / "model.onnx"
    torch.onnx.export(
        wrapped, dummy, str(out), opset_version=args.opset,
        input_names=["wave"], output_names=["logits"],
        dynamic_axes={"wave": {1: "samples"}, "logits": {1: "frames"}},
        dynamo=False,
    )
    print(f"wrote {out} ({out.stat().st_size / 2**20:.0f} MB)")

    import onnxruntime as ort
    sess = ort.InferenceSession(str(out), providers=["CPUExecutionProvider"])
    worst = 0.0
    for seconds in (1.7, 3.0, 6.2, 9.9):
        wave = torch.randn(1, int(16000 * seconds))
        with torch.no_grad():
            ref = wrapped(wave).numpy()
        got = sess.run(None, {"wave": wave.numpy()})[0]
        assert ref.shape == got.shape, (ref.shape, got.shape)
        worst = max(worst, float(np.abs(ref - got).max()))
    print(f"max abs logits diff vs torch: {worst:.2e}")
    assert worst < 1e-3, "ONNX export diverges from torch"


if __name__ == "__main__":
    main()
