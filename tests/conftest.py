"""Shared test fixtures for the pronunciation validation service."""
from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
import torch
from httpx import ASGITransport, AsyncClient

from app.models.schemas import (
    ErrorType,
    EvaluationResult,
    PhonemeResult,
    PronunciationLevel,
    PronunciationResponse,
    WordResult,
)

# ── Fake / mock services ────────────────────────────────────────────────────


def _make_fake_asr():
    """Create a mock ASRService that avoids loading the real model."""
    asr = MagicMock()
    asr.transcribe.return_value = "hello world"
    # Vocabulary: <pad>=0, <s>=1, </s>=2, <unk>=3, |=4, A-Z=5..30 → 31 entries
    # Emission tensors must use V=31 to match this vocab size.
    vocab: dict[str, int] = {"<pad>": 0, "<s>": 1, "</s>": 2, "<unk>": 3, "|": 4}
    vocab.update({chr(c): i for i, c in enumerate(range(65, 91), start=5)})
    n_vocab = len(vocab)  # 31
    # Return a (T=50, V=31) log-prob tensor
    asr.get_ctc_log_probs.return_value = torch.randn(50, n_vocab)
    # get_emission returns (1, T, V) for forced alignment
    asr.get_emission.return_value = torch.randn(1, 50, n_vocab)
    asr.get_vocab.return_value = vocab
    return asr


def _make_fake_ipa():
    """Create a mock IPAService that avoids loading g2p_en."""
    ipa = MagicMock()
    ipa.text_to_ipa.side_effect = lambda text: " ".join(
        {"hello": "hɛloʊ", "world": "wɝld", "cat": "kæt", "the": "ðə"}.get(
            w, w
        )
        for w in text.lower().split()
    )
    ipa.word_to_ipa.side_effect = lambda w: {
        "hello": "hɛloʊ",
        "world": "wɝld",
        "cat": "kæt",
        "the": "ðə",
    }.get(w.lower(), w)
    ipa.word_to_phoneme_list.side_effect = lambda w: {
        "hello": ["h", "ɛ", "l", "oʊ"],
        "world": ["w", "ɝ", "l", "d"],
        "cat": ["k", "æ", "t"],
        "the": ["ð", "ə"],
    }.get(w.lower(), list(w))
    return ipa


@pytest.fixture
def fake_asr():
    return _make_fake_asr()


@pytest.fixture
def fake_ipa():
    return _make_fake_ipa()


# ── Test audio data ──────────────────────────────────────────────────────────


@pytest.fixture
def sample_waveform() -> np.ndarray:
    """1-second 16 kHz sine-wave audio."""
    sr = 16000
    t = np.linspace(0, 1.0, sr, dtype=np.float32)
    return np.sin(2 * np.pi * 440 * t)


@pytest.fixture
def sample_audio_bytes(sample_waveform) -> bytes:
    """WAV bytes from the sample waveform."""
    import io

    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, sample_waveform, 16000, format="WAV")
    return buf.getvalue()


# ── Fake PronunciationResponse ───────────────────────────────────────────────


def make_fake_pronunciation_response() -> PronunciationResponse:
    """Build a realistic PronunciationResponse for route tests."""
    return PronunciationResponse(
        reference_text="hello",
        transcribed_text="hello",
        results=EvaluationResult(
            reference_ipa="hɛloʊ",
            actual_ipa="hɛloʊ",
            word_details=[
                WordResult(
                    word="hello",
                    expected_ipa="hɛloʊ",
                    actual_ipa="hɛloʊ",
                    phoneme_details=[
                        PhonemeResult(
                            expected_ipa="h",
                            actual_ipa="h",
                            is_correct_ipa=True,
                            confidence_ipa=1.0,
                            gop_score=85.0,
                            gop_quality=PronunciationLevel.EXCELLENT,
                        ),
                    ],
                    ipa_accuracy=100.0,
                    word_gop_score=85.0,
                    word_gop_quality=PronunciationLevel.EXCELLENT,
                    error_type=ErrorType.NONE,
                )
            ],
            overall_ipa_accuracy=100.0,
            overall_gop_score=85.0,
            overall_gop_quality=PronunciationLevel.EXCELLENT,
        ),
        accuracy_score=93.25,
        completeness_score=100.0,
        fluency_score=100.0,
        prosody_score=100.0,
        overall_score=97.98,
        level=PronunciationLevel.EXCELLENT,
        feedback="Excellent pronunciation! Score: 97.98/100.",
    )


# ── FastAPI test client ──────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Create the FastAPI app (ML models loaded from singletons)."""
    from app.application import create_app

    return create_app()


@pytest.fixture
async def client(app):
    """Async HTTP client for integration tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
