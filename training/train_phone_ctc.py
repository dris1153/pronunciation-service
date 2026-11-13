"""Fine-tune HuBERT-base into a 41-phone IPA CTC model on native LibriSpeech.

    python -m training.train_phone_ctc --steps 25000

Native speech only: training on L2 audio with canonical labels would teach the
model to forgive pronunciation errors.
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import HubertForCTC

from training.data import BatchLoader, build_manifest, make_batches
from training.eval_per import evaluate
from training.phone_labels import VOCAB

ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=ROOT / "data" / "librispeech")
    p.add_argument("--out", type=Path, default=ROOT / "data" / "models" / "hubert-phone-ctc")
    p.add_argument("--base", default="facebook/hubert-base-ls960")
    p.add_argument("--train-split", default="train-clean-100")
    p.add_argument("--dev-split", default="dev-clean")
    p.add_argument("--steps", type=int, default=25000, help="optimizer steps")
    p.add_argument("--batch-seconds", type=float, default=100.0)
    p.add_argument("--accum", type=int, default=2, help="micro-batches per optimizer step")
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--head-lr", type=float, default=1e-3)
    p.add_argument("--freeze-steps", type=int, default=1000, help="train only the head first")
    p.add_argument("--eval-every", type=int, default=2000)
    p.add_argument("--dev-limit", type=int, default=0, help="dev utterances for periodic eval (0 = all)")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--grad-ckpt", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    return p.parse_args()


def lr_scale(step: int, total: int, warmup: int) -> float:
    if step < warmup:
        return step / max(1, warmup)
    return max(0.0, (total - step) / max(1, total - warmup))


def main() -> None:
    args = parse_args()
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "vocab.json").write_text(json.dumps(VOCAB, ensure_ascii=False), encoding="utf-8")

    train = build_manifest(args.root, args.train_split)
    dev = build_manifest(args.root, args.dev_split)
    dev = dev[:: max(1, len(dev) // args.dev_limit)] if args.dev_limit else dev

    model = HubertForCTC.from_pretrained(
        args.base, vocab_size=len(VOCAB), pad_token_id=0, layerdrop=0.0,
        mask_time_prob=0.05, ignore_mismatched_sizes=True,
    ).to(device)
    model.freeze_feature_encoder()
    if args.grad_ckpt:
        model.gradient_checkpointing_enable()
    head = list(model.lm_head.parameters())
    head_ids = {id(p) for p in head}
    body = [p for p in model.parameters() if p.requires_grad and id(p) not in head_ids]
    opt = torch.optim.AdamW(
        [{"params": body, "lr": args.lr}, {"params": head, "lr": args.head_lr}],
        weight_decay=0.01,
    )
    base_lrs = [args.lr, args.head_lr]
    warmup = args.steps // 10

    step, micro, best_per, t0 = 0, 0, 1.0, time.time()
    log = args.out / "train-log.jsonl"
    while step < args.steps:
        loader = torch.utils.data.DataLoader(
            BatchLoader(make_batches(train, args.batch_seconds, shuffle=True)),
            batch_size=None, num_workers=args.workers, prefetch_factor=4 if args.workers else None,
        )
        for batch in loader:
            model.train()
            for p in body:
                p.requires_grad_(step >= args.freeze_steps)
            with torch.autocast(device, dtype=torch.bfloat16):
                logits = model(batch["inputs"].to(device)).logits
            log_probs = F.log_softmax(logits.float(), dim=-1).transpose(0, 1)  # (T, B, V)
            out_lens = model._get_feat_extract_output_lengths(batch["input_lengths"])
            loss = F.ctc_loss(
                log_probs, batch["targets"], out_lens, batch["target_lengths"],
                blank=0, zero_infinity=True,
            )
            (loss / args.accum).backward()
            micro += 1
            if micro % args.accum:
                continue

            for g, base in zip(opt.param_groups, base_lrs):
                g["lr"] = base * lr_scale(step, args.steps, warmup)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            opt.zero_grad(set_to_none=True)
            step += 1

            if step % 100 == 0:
                print(f"step {step}/{args.steps} loss {loss.item():.3f} "
                      f"{(time.time() - t0) / 60:.1f} min", flush=True)
            if step % args.eval_every == 0 or step == args.steps:
                res = evaluate(model, dev, device)
                res |= {"step": step, "loss": loss.item(), "minutes": (time.time() - t0) / 60,
                        "vram_gb": torch.cuda.max_memory_allocated() / 2**30}
                print(res, flush=True)
                with log.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(res) + "\n")
                if res["per"] < best_per:
                    best_per = res["per"]
                    model.save_pretrained(args.out)
            if step >= args.steps:
                break


if __name__ == "__main__":
    main()
