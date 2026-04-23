"""Tests for all API endpoints (mocked services where needed)."""
from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import verify_api_key
from app.application import create_app
from app.models.schemas import (
    ErrorType,
    EvaluationResult,
    PhonemeResult,
    PronunciationLevel,
    PronunciationResponse,
    WordResult,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def app():
    """Create app with auth disabled via dependency_overrides."""
    application = create_app()
    application.dependency_overrides[verify_api_key] = lambda: None
    return application


@pytest.fixture
def app_no_override():
    """Create app WITHOUT auth override — for auth enforcement tests."""
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def raw_client(app_no_override):
    """Client without auth override."""
    transport = ASGITransport(app=app_no_override)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def _fake_pronunciation_response() -> PronunciationResponse:
    """Build a realistic mock response for /evaluate."""
    return PronunciationResponse(
        reference_text="hello",
        transcribed_text="hello",
        accuracy_score=93.25,
        completeness_score=100.0,
        fluency_score=100.0,
        prosody_score=100.0,
        overall_score=97.98,
        level=PronunciationLevel.EXCELLENT,
        feedback="Excellent pronunciation! Score: 97.98/100.",
        results=EvaluationResult(
            reference_ipa="hɛloʊ",
            actual_ipa="hɛloʊ",
            overall_ipa_accuracy=90.0,
            overall_gop_score=82.0,
            overall_gop_quality=PronunciationLevel.EXCELLENT,
            word_details=[
                WordResult(
                    word="hello",
                    expected_ipa="hɛloʊ",
                    actual_ipa="hɛloʊ",
                    ipa_accuracy=90.0,
                    word_gop_score=82.0,
                    word_gop_quality=PronunciationLevel.EXCELLENT,
                    error_type=ErrorType.NONE,
                    phoneme_details=[
                        PhonemeResult(
                            expected_ipa="h",
                            actual_ipa="h",
                            is_correct_ipa=True,
                            confidence_ipa=0.95,
                            gop_score=85.0,
                            gop_quality=PronunciationLevel.EXCELLENT,
                        ),
                    ],
                )
            ],
        ),
    )


# ── Health endpoint ──────────────────────────────────────────────────────────


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_body_contains_status(self, client: AsyncClient):
        resp = await client.get("/health")
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data


# ── Model-info endpoint ─────────────────────────────────────────────────────


class TestModelInfoEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, client: AsyncClient):
        resp = await client.get("/api/v1/model-info")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_body_shape(self, client: AsyncClient):
        data = (await client.get("/api/v1/model-info")).json()
        assert "asr_model" in data
        assert "supported_formats" in data
        assert isinstance(data["supported_formats"], list)
        assert "max_upload_mb" in data
        assert "sample_rate" in data


# ── Text-analysis endpoint ──────────────────────────────────────────────────


class TestTextAnalysisEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200_with_valid_text(self, client: AsyncClient):
        resp = await client.get("/api/v1/text-analysis", params={"text": "hello"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_body_contains_words(self, client: AsyncClient):
        resp = await client.get("/api/v1/text-analysis", params={"text": "hello world"})
        data = resp.json()
        assert "ipa" in data
        assert "words" in data
        assert len(data["words"]) == 2

    @pytest.mark.asyncio
    async def test_missing_text_param(self, client: AsyncClient):
        resp = await client.get("/api/v1/text-analysis")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_word_detail_has_phonemes(self, client: AsyncClient):
        resp = await client.get("/api/v1/text-analysis", params={"text": "cat"})
        data = resp.json()
        word = data["words"][0]
        assert "ipa" in word
        assert "phonemes" in word
        assert isinstance(word["phonemes"], list)


# ── Transcribe endpoint ─────────────────────────────────────────────────────


class TestTranscribeEndpoint:
    @pytest.mark.asyncio
    async def test_no_audio_returns_422(self, client: AsyncClient):
        resp = await client.post("/api/v1/transcribe")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    @patch("app.api.routes.transcribe._transcribe_sync")
    async def test_valid_audio_returns_200(self, mock_sync, client: AsyncClient):
        mock_sync.return_value = ("hello", 1.0)

        audio = io.BytesIO(b"\x00" * 100)
        resp = await client.post(
            "/api/v1/transcribe",
            files={"audio": ("test.wav", audio, "audio/wav")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["transcription"] == "hello"
        assert data["duration_sec"] == 1.0


# ── Evaluate endpoint ───────────────────────────────────────────────────────


class TestEvaluateEndpoint:
    @pytest.mark.asyncio
    async def test_no_audio_returns_422(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/evaluate", data={"reference_text": "hello"}
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_empty_reference_rejected(self, client: AsyncClient):
        audio = io.BytesIO(b"\x00" * 100)
        resp = await client.post(
            "/api/v1/evaluate",
            data={"reference_text": ""},
            files={"audio": ("test.wav", audio, "audio/wav")},
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_valid_request_returns_200(self, app, client: AsyncClient):
        from app.api.dependencies import get_pronunciation_svc

        fake_svc = MagicMock()
        fake_svc.evaluate = AsyncMock(return_value=_fake_pronunciation_response())
        app.dependency_overrides[get_pronunciation_svc] = lambda: fake_svc

        audio = io.BytesIO(b"\x00" * 100)
        resp = await client.post(
            "/api/v1/evaluate",
            data={"reference_text": "hello"},
            files={"audio": ("test.wav", audio, "audio/wav")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "overall_score" in data
        assert "accuracy_score" in data
        assert "completeness_score" in data
        assert "fluency_score" in data
        assert "prosody_score" in data
        assert "results" in data
        assert "overall_ipa_accuracy" in data["results"]
        assert "overall_gop_score" in data["results"]

    @pytest.mark.asyncio
    async def test_wrong_content_type_rejected(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/evaluate",
            content=b"not multipart",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code in (400, 422)


# ── Auth enforcement ─────────────────────────────────────────────────────────


class TestAuthEnforcement:
    """When API_KEY is set, protected routes must reject missing / wrong keys."""

    @pytest.mark.asyncio
    @patch("app.api.dependencies.get_settings")
    async def test_evaluate_401_without_key(self, mock_settings, raw_client: AsyncClient):
        mock_settings.return_value = MagicMock(api_key="secret123")
        audio = io.BytesIO(b"\x00" * 100)
        resp = await raw_client.post(
            "/api/v1/evaluate",
            data={"reference_text": "hello"},
            files={"audio": ("test.wav", audio, "audio/wav")},
        )
        assert resp.status_code in (401, 403, 422)

    @pytest.mark.asyncio
    async def test_health_always_public(self, raw_client: AsyncClient):
        resp = await raw_client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_model_info_always_public(self, raw_client: AsyncClient):
        resp = await raw_client.get("/api/v1/model-info")
        assert resp.status_code == 200
