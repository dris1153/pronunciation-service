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
        self.device = torch.device(settings.device)

        logger.info("Loading ASR model '{}' → {}", model_name, self.device)
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
            self.model: Wav2Vec2ForCTC = Wav2Vec2ForCTC.from_pretrained(
                model_name,
                cache_dir=cache_dir,
            ).to(self.device)
        self.model.eval()
        logger.info("ASR model loaded successfully")

    # ── public API ───────────────────────────────────────────

    @torch.no_grad()
    def transcribe(self, waveform: np.ndarray, sr: int) -> str:
        """Return plain-text transcription."""
        logits = self._get_logits(waveform, sr)
        predicted_ids = torch.argmax(logits, dim=-1)
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
