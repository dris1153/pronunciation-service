"""Phone error rate (PER) of a phone CTC checkpoint.

    python -m training.eval_per --model data/models/hubert-phone-ctc --split test-clean
"""
from __future__ import annotations

import argparse
from pathlib import Path

import torch
from transformers import HubertForCTC

from training.data import BatchLoader, Utt, build_manifest, make_batches

ROOT = Path(__file__).resolve().parent.parent


def edit_distance(a: list[int], b: list[int]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def greedy_decode(logits: torch.Tensor, n_frames: int) -> list[int]:
    """argmax, collapse repeats, drop blank (id 0)."""
    ids = logits[:n_frames].argmax(-1).tolist()
    out: list[int] = []
    prev = -1
    for i in ids:
        if i != prev and i != 0:
            out.append(i)
        prev = i
    return out


@torch.no_grad()
def evaluate(model: HubertForCTC, utts: list[Utt], device: str, batch_seconds: float = 120.0) -> dict:
    model.eval()
    loader = torch.utils.data.DataLoader(
        BatchLoader(make_batches(utts, batch_seconds, shuffle=False)),
        batch_size=None, num_workers=2,
    )
    errors = total = blank_frames = frames = 0
    for batch in loader:
        with torch.autocast(device, dtype=torch.bfloat16, enabled=device == "cuda"):
            logits = model(batch["inputs"].to(device)).logits.float()
        out_lens = model._get_feat_extract_output_lengths(batch["input_lengths"]).tolist()
        for i, ref in enumerate(batch["labels"]):
            hyp = greedy_decode(logits[i].cpu(), out_lens[i])
            errors += edit_distance(ref, hyp)
            total += len(ref)
            argmax = logits[i, : out_lens[i]].argmax(-1)
            blank_frames += int((argmax == 0).sum())
            frames += out_lens[i]
    return {"per": errors / total, "blank_frame_ratio": blank_frames / frames, "n_phones": total}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", type=Path, default=ROOT / "data" / "models" / "hubert-phone-ctc")
    p.add_argument("--split", default="test-clean")
    p.add_argument("--root", type=Path, default=ROOT / "data" / "librispeech")
    args = p.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = HubertForCTC.from_pretrained(args.model).to(device)
    print(evaluate(model, build_manifest(args.root, args.split), device))


if __name__ == "__main__":
    main()
