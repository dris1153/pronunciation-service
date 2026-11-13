"""ONNX phone CTC model: waveform -> per-frame log-posteriors (torch-free)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import onnxruntime as ort

from app.utils.audio import normalize_audio

FRAME_MS = 20  # HuBERT conv stride: 320 samples @ 16 kHz
MIN_SAMPLES = 400  # the conv front-end rejects anything shorter (25 ms)


class PhoneModel:
    def __init__(self, model_dir: Path, int8: bool = False, intra_op_threads: int = 0) -> None:
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = intra_op_threads
        opts.inter_op_num_threads = 1
        opts.enable_mem_pattern = False  # input length differs per request
        opts.enable_cpu_mem_arena = True
        model_path = model_dir / ("model.int8.onnx" if int8 else "model.onnx")
        # onnxruntime raises its own NoSuchFile, which callers can't tell from a corrupt model
        for path in (model_path, model_dir / "vocab.json"):
            if not path.exists():
                raise FileNotFoundError(str(path))
        self._sess = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self.vocab: list[str] = json.loads((model_dir / "vocab.json").read_text(encoding="utf-8"))

    def log_posteriors(self, waveform: np.ndarray) -> np.ndarray:
        """16 kHz mono float32 -> (T, V) log-softmax; blank is index 0."""
        if len(waveform) < MIN_SAMPLES:
            raise ValueError("Audio is too short to analyse.")
        wave = normalize_audio(np.asarray(waveform, dtype=np.float32))[None, :]
        logits = self._sess.run(None, {"wave": wave})[0][0].astype(np.float64)
        logits -= logits.max(axis=-1, keepdims=True)
        return logits - np.log(np.exp(logits).sum(axis=-1, keepdims=True))
