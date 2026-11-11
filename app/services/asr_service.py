"""ASR (Automatic Speech Recognition) service.

Wraps HuggingFace **Wav2Vec2** to transcribe audio and expose CTC
log-probabilities needed for GOP scoring.
"""
from __future__ import annotations

import warnings
from functools import lru_cache

import numpy as np
import torch
from loguru import logger
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

from app.core.config import get_settings


class ASRService:
    """Wav2Vec2-based speech recognition service."""

    def __init__(self) -> None:
        settings = get_settings()
        model_name = settings.asr_model_name
        cache_dir = settings.asr_model_cache_dir
        backend = settings.inference_backend
        # INT8 quantize_dynamic only supports CPU; force device override.
        self.device = torch.device("cpu" if backend == "torch_int8" else settings.device)

        logger.info(
            "Loading ASR model '{}' → device={} backend={}",
            model_name, self.device, backend,
        )
        self.processor: Wav2Vec2Processor = Wav2Vec2Processor.from_pretrained(
            model_name, cache_dir=cache_dir
        )
        # Suppress the "Some weights were not initialized" warning for
        # `wav2vec2.masked_spec_embed`. This parameter is only used during
        # training (masked spectrogram augmentation) and has no effect on
        # inference. The warning is a false alarm for a fully fine-tuned model.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Some weights of Wav2Vec2ForCTC were not initialized",
            )
            model: Wav2Vec2ForCTC = Wav2Vec2ForCTC.from_pretrained(
                model_name,
                cache_dir=cache_dir,
            )

        if backend == "torch_int8":
            # Dynamic INT8 quantization on Linear layers. The 7 Conv1d
            # feature-extractor layers are NOT quantized — see Phase 03
            # spike notes for realistic 1.1-1.4× speedup expectation.
            from torch.quantization import quantize_dynamic

            model = quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
            logger.info("ASR model quantized to INT8 (Linear layers only)")
        else:
            model = model.to(self.device)

        model.eval()
        self.model = model
        logger.info("ASR model loaded successfully")

    # ── public API ───────────────────────────────────────────

    @torch.no_grad()
    def transcribe(self, waveform: np.ndarray, sr: int) -> str:
        """Return plain-text transcription."""
        return self.decode(self._get_logits(waveform, sr))

    def decode(self, emission: torch.Tensor) -> str:
        """Greedy CTC decode of logits or log-probs shaped (1, T, V).

        argmax of logits and of their log_softmax agree (up to float32 ties), so
        callers that already hold the emission can skip a second forward pass.
        """
        predicted_ids = torch.argmax(emission, dim=-1)
        transcription: str = self.processor.batch_decode(predicted_ids)[0]
        return transcription.strip().lower()

    @torch.no_grad()
    def get_ctc_log_probs(self, waveform: np.ndarray, sr: int) -> torch.Tensor:
        """Return CTC log-probabilities (T × V) for GOP computation."""
        logits = self._get_logits(waveform, sr)
        log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
        return log_probs.squeeze(0)  # (T, V)

    @torch.no_grad()
    def get_emission(self, waveform: np.ndarray, sr: int) -> torch.Tensor:
        """Return CTC log-probabilities as (1, T, V) for forced alignment.

        ``torchaudio.functional.forced_align`` expects a batched tensor
        ``(B, T, C)`` with log-probabilities, so we keep the batch dim.
        """
        logits = self._get_logits(waveform, sr)
        return torch.nn.functional.log_softmax(logits, dim=-1)  # (1, T, V)

    def get_vocab(self) -> dict[str, int]:
        """Return the processor's vocabulary {token: index}."""
        return self.processor.tokenizer.get_vocab()

    # ── internals ────────────────────────────────────────────

    def _get_logits(self, waveform: np.ndarray, sr: int) -> torch.Tensor:
        inputs = self.processor(
            waveform, sampling_rate=sr, return_tensors="pt", padding=True
        )
        input_values = inputs.input_values.to(self.device)
        logits = self.model(input_values).logits
        return logits


@lru_cache
def get_asr_service() -> ASRService:
    return ASRService()
