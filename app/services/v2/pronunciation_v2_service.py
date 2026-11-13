"""v2 pronunciation evaluation: phone CTC analysis + learned scorer -> v1-shaped response (torch-free)."""
from __future__ import annotations

import asyncio
import time
from functools import lru_cache
from pathlib import Path

from loguru import logger

from app.core.config import get_settings
from app.models.schemas import (
    ErrorType,
    EvaluationResultV2,
    GOPResult,
    PhonemeResult,
    PronunciationLevel,
    PronunciationResponseV2,
    WordGOP,
    WordResultV2,
)
from app.services.ipa_service import IPAService, get_ipa_service
from app.services.phoneme_align import _phoneme_similarity
from app.services.scoring_rules import (
    _MISPRONUNCIATION_THRESHOLD,
    _build_feedback,
    _detect_missing_breaks,
    _detect_unexpected_breaks,
    _level_from_score,
)
from app.services.v2.analyser import V2Analyser, get_v2_analyser
from app.services.v2.gop_features import V2Analysis, WordAnalysis
from app.services.v2.phone_model import FRAME_MS
from app.services.v2.scorer import Scorer, Scores
from app.utils.audio import is_silent, load_audio_from_bytes, validate_audio_duration
from app.utils.text import text_to_words

# The scorer predicts on the speechocean762 expert scale (mostly 6-10 out of 10). Raising every
# utterance-level score (accuracy, fluency, prosody, total) to this power moves it onto the stricter v1/Azure scale: poor sanity clips drop below 60
# while good ones stay above 70 (1.3 left poor_001 at 59.4, too close to the line).
SCORE_CURVE_EXPONENT = 1.4


def remap_score(score_0_10: float) -> float:
    """Expert-scale 0-10 prediction -> 0-100 on the stricter service scale."""
    return round(100.0 * (min(max(score_0_10, 0.0), 10.0) / 10.0) ** SCORE_CURVE_EXPONENT, 2)


def _clip100(x: float) -> float:
    return round(min(max(x, 0.0), 100.0), 2)


class PronunciationV2Service:
    def __init__(
        self, analyser: V2Analyser | None = None, scorer: Scorer | None = None, ipa: IPAService | None = None
    ) -> None:
        self._analyser = analyser or get_v2_analyser()
        self._scorer = scorer or Scorer.load(Path(get_settings().phone_model_dir) / "scorer.json")
        self._ipa = ipa or get_ipa_service()
        logger.info("PronunciationV2Service ready")

    async def evaluate(self, audio_bytes: bytes, reference_text: str) -> PronunciationResponseV2:
        from app.core.concurrency import inference_semaphore

        async with inference_semaphore():
            return await asyncio.to_thread(self._evaluate_sync, audio_bytes, reference_text)

    def _evaluate_sync(self, audio_bytes: bytes, reference_text: str) -> PronunciationResponseV2:
        start = time.perf_counter()
        waveform, sr = load_audio_from_bytes(audio_bytes)
        validate_audio_duration(waveform, sr)
        if is_silent(waveform):
            logger.warning("Silent audio detected — returning zero-score response")
            return self._zero_score_response(reference_text)

        analysis = self._analyser.analyse(waveform, reference_text)
        scores = self._scorer.score(analysis)
        response = self._build_response(reference_text, analysis, scores)
        logger.bind(stage_ms={"total": round((time.perf_counter() - start) * 1000, 1)}).info("evaluate_timing")
        return response

    # ── response assembly ────────────────────────────────────

    def _build_response(self, reference_text: str, a: V2Analysis, scores: Scores) -> PronunciationResponseV2:
        words = [self._word_result(w, ps, ws) for w, ps, ws in zip(a.words, scores.phone, scores.word)]
        self._apply_break_errors(words, a, reference_text)

        phones = [p for w in words for p in w.phoneme_details if p.expected_ipa]
        n = max(1, len(phones))
        overall_gop = _clip100(sum(p.gop_score for p in phones) / n)
        actual_ipa = " ".join(w.actual_ipa for w in words)
        total = remap_score(scores.utt["total"])
        level = _level_from_score(total)
        results = EvaluationResultV2(
            reference_ipa=self._ipa.text_to_ipa(reference_text),
            actual_ipa=actual_ipa,
            word_details=words,
            overall_ipa_accuracy=_clip100(100 * sum(p.is_correct_ipa for p in phones) / n),
            overall_gop_score=overall_gop,
            overall_gop_quality=_level_from_score(overall_gop),
        )
        return PronunciationResponseV2(
            reference_text=reference_text,
            transcribed_text=actual_ipa,
            results=results,
            accuracy_score=remap_score(scores.utt["accuracy"]),
            completeness_score=_clip100(scores.completeness * 10),
            fluency_score=remap_score(scores.utt["fluency"]),
            prosody_score=remap_score(scores.utt["prosodic"]),
            overall_score=total,
            level=level,
            feedback=_build_feedback(level, total),
        )

    def _word_result(self, w: WordAnalysis, phone_scores: list[float], word_score: float) -> WordResultV2:
        details: list[PhonemeResult] = []
        for ph, s in zip(w.phones, phone_scores):
            gop = _clip100(s * 50)
            details.append(PhonemeResult(
                expected_ipa=ph.expected, actual_ipa=ph.heard,
                is_correct_ipa=s >= self._scorer.mdd_threshold,
                confidence_ipa=_phoneme_similarity(ph.expected, ph.heard) if ph.heard else 0.0,
                gop_score=gop, gop_quality=_level_from_score(gop),
            ))
        details += [
            PhonemeResult(expected_ipa="", actual_ipa=a, is_correct_ipa=False, confidence_ipa=0.0,
                          gop_score=0.0, gop_quality=PronunciationLevel.POOR)
            for a in w.inserted
        ]
        scored = [d for d in details if d.expected_ipa]
        word_gop = _clip100(word_score * 10)
        if w.phones and all(p.heard == "" for p in w.phones):
            error = ErrorType.OMISSION
        elif word_gop < _MISPRONUNCIATION_THRESHOLD:
            error = ErrorType.MISPRONUNCIATION
        else:
            error = ErrorType.NONE
        return WordResultV2(
            word=w.word,
            expected_ipa=self._ipa.word_to_ipa(w.word),
            actual_ipa="".join(p.heard for p in w.phones),
            phoneme_details=details,
            ipa_accuracy=_clip100(100 * sum(d.is_correct_ipa for d in scored) / max(1, len(scored))),
            word_gop_score=word_gop,
            word_gop_quality=_level_from_score(word_gop),
            error_type=error,
            start_ms=w.start * FRAME_MS,
            end_ms=w.end * FRAME_MS,
        )

    @staticmethod
    def _apply_break_errors(words: list[WordResultV2], a: V2Analysis, reference_text: str) -> None:
        """Same pause rules as v1, driven by the forced-alignment word spans (20 ms frames, as in v1)."""
        gop = GOPResult(
            word_scores=[
                WordGOP(word=w.word, word_gop_score=0.0, quality=PronunciationLevel.POOR,
                        start_frame=w.start, end_frame=w.end)
                for w in a.words
            ],
            overall_gop_score=0.0, overall_quality=PronunciationLevel.POOR,
            sample_rate=16000, total_frames=a.n_frames,
        )
        for i in _detect_unexpected_breaks(gop):
            if words[i].error_type in (ErrorType.NONE, ErrorType.MISPRONUNCIATION):
                words[i].error_type = ErrorType.UNEXPECTED_BREAK
        for i in _detect_missing_breaks(gop, reference_text):
            if words[i].error_type == ErrorType.NONE:
                words[i].error_type = ErrorType.MISSING_BREAK

    def _zero_score_response(self, reference_text: str) -> PronunciationResponseV2:
        words = [
            WordResultV2(
                word=w, expected_ipa=self._ipa.word_to_ipa(w), actual_ipa="", phoneme_details=[],
                ipa_accuracy=0.0, word_gop_score=0.0, word_gop_quality=PronunciationLevel.POOR,
                error_type=ErrorType.OMISSION, start_ms=0, end_ms=0,
            )
            for w in text_to_words(reference_text)
        ]
        results = EvaluationResultV2(
            reference_ipa=self._ipa.text_to_ipa(reference_text), actual_ipa="", word_details=words,
            overall_ipa_accuracy=0.0, overall_gop_score=0.0, overall_gop_quality=PronunciationLevel.POOR,
        )
        return PronunciationResponseV2(
            reference_text=reference_text, transcribed_text="", results=results,
            accuracy_score=0.0, completeness_score=0.0, fluency_score=0.0, prosody_score=0.0,
            overall_score=0.0, level=PronunciationLevel.POOR,
            feedback=_build_feedback(PronunciationLevel.POOR, 0.0),
        )


@lru_cache(maxsize=1)
def get_pronunciation_v2_service() -> PronunciationV2Service:
    return PronunciationV2Service()
