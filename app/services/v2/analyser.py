"""v2 analysis core: audio + reference text -> per-word/phone GOP features and heard phones."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.services.ipa_service import get_ipa_service
from app.services.v2.gop_features import V2Analysis, analyse_posteriors
from app.services.v2.phone_model import PhoneModel
from app.utils.text import text_to_words


class V2Analyser:
    def __init__(self, model_dir: Path) -> None:
        self._model = PhoneModel(model_dir)
        self._ipa = get_ipa_service()

    def analyse(self, waveform: np.ndarray, reference_text: str) -> V2Analysis:
        words = [(w, self._ipa.word_to_phoneme_list(w)) for w in text_to_words(reference_text)]
        return analyse_posteriors(self._model.log_posteriors(waveform), words, self._model.vocab)


@lru_cache(maxsize=1)
def get_v2_analyser() -> V2Analyser:
    return V2Analyser(Path(get_settings().phone_model_dir))
