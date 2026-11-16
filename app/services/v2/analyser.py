"""v2 analysis core: audio + reference text -> per-word/phone GOP features and heard phones."""
from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.concurrency import torch_threads_per_slot  # pure CPU math despite the name
from app.core.config import get_settings
from app.services.ipa_service import get_ipa_service
from app.services.v2.gop_features import V2Analysis, analyse_posteriors
from app.services.v2.phone_model import PhoneModel
from app.utils.text import text_to_words


class V2Analyser:
    def __init__(self, model_dir: Path, int8: bool = False, threads: int = 0) -> None:
        self._model = PhoneModel(model_dir, int8, threads)
        self._ipa = get_ipa_service()

    def analyse(
        self, waveform: np.ndarray, reference_text: str, lap: Callable[[str], None] | None = None
    ) -> V2Analysis:
        lap = lap or (lambda _stage: None)
        words = [(w, self._ipa.word_to_phoneme_list(w)) for w in text_to_words(reference_text)]
        lap("g2p")
        posteriors = self._model.log_posteriors(waveform)
        lap("model")
        analysis = analyse_posteriors(posteriors, words, self._model.vocab)
        lap("align")
        return analysis


@lru_cache(maxsize=1)
def get_v2_analyser() -> V2Analyser:
    settings = get_settings()
    return V2Analyser(Path(settings.phone_model_dir), settings.phone_model_int8, torch_threads_per_slot())
