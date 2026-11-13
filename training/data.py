"""LibriSpeech manifests, length-bucketed batches and waveform loading."""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

from training.phone_labels import words_to_ids

SAMPLE_RATE = 16000
MAX_SECONDS = 20.0  # longer utterances only waste memory in CTC training


@dataclass
class Utt:
    id: str
    path: str
    seconds: float
    ids: list[int]


def build_manifest(root: Path, split: str) -> list[Utt]:
    """Scan ``root/LibriSpeech/<split>`` once; cached next to the audio."""
    cache = root / f"{split}.manifest.jsonl"
    if cache.exists():
        return [Utt(**json.loads(line)) for line in cache.read_text(encoding="utf-8").splitlines()]

    utts: list[Utt] = []
    dropped = 0
    for trans in sorted((root / "LibriSpeech" / split).glob("*/*/*.trans.txt")):
        for line in trans.read_text(encoding="utf-8").splitlines():
            utt_id, _, text = line.partition(" ")
            path = trans.parent / f"{utt_id}.flac"
            ids, bad = words_to_ids(text)
            dropped += bad
            if ids:
                utts.append(Utt(utt_id, str(path), sf.info(str(path)).duration, ids))
    cache.write_text(
        "\n".join(json.dumps(u.__dict__) for u in utts) + "\n", encoding="utf-8"
    )
    print(f"{split}: {len(utts)} utts, {sum(u.seconds for u in utts) / 3600:.1f} h, "
          f"{dropped} g2p symbols dropped")
    return utts


def load_wave(path: str) -> np.ndarray:
    """Mono float32, peak-normalised — the same input contract as the service
    (``normalize_audio``); no mean/variance normalisation (HuBERT base)."""
    wave, sr = sf.read(path, dtype="float32")
    assert sr == SAMPLE_RATE, f"{path}: expected 16 kHz, got {sr}"
    peak = float(np.max(np.abs(wave)))
    return wave / peak if peak > 0 else wave


def make_batches(utts: list[Utt], batch_seconds: float, shuffle: bool) -> list[list[Utt]]:
    """Group utterances of similar length so zero padding stays small."""
    ordered = sorted((u for u in utts if u.seconds <= MAX_SECONDS), key=lambda u: u.seconds)
    batches: list[list[Utt]] = []
    cur: list[Utt] = []
    for u in ordered:
        # sorted ascending → u is the longest in the batch once appended
        if cur and u.seconds * (len(cur) + 1) > batch_seconds:
            batches.append(cur)
            cur = []
        cur.append(u)
    if cur:
        batches.append(cur)
    if shuffle:
        random.shuffle(batches)
    return batches


def collate(batch: list[Utt]) -> dict:
    waves = [load_wave(u.path) for u in batch]
    lengths = torch.tensor([len(w) for w in waves])
    inputs = torch.zeros(len(waves), int(lengths.max()))
    for i, w in enumerate(waves):
        inputs[i, : len(w)] = torch.from_numpy(w)
    return {
        "inputs": inputs,
        "input_lengths": lengths,
        "targets": torch.tensor([i for u in batch for i in u.ids]),
        "target_lengths": torch.tensor([len(u.ids) for u in batch]),
        "labels": [u.ids for u in batch],
    }


class BatchLoader(torch.utils.data.Dataset):
    """One item = one pre-built batch, so DataLoader workers prefetch whole batches."""

    def __init__(self, batches: list[list[Utt]]) -> None:
        self.batches = batches

    def __len__(self) -> int:
        return len(self.batches)

    def __getitem__(self, i: int) -> dict:
        return collate(self.batches[i])
