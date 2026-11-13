import io
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from httpx import AsyncClient

from app.api.dependencies import get_pronunciation_v2_svc
from app.models.schemas import PronunciationResponse
from app.services.v2.gop_features import PhoneAnalysis, V2Analysis, WordAnalysis
from app.services.v2.pronunciation_v2_service import PronunciationV2Service
from app.services.v2.scorer import Scores


def _v2_response():
    ipa = MagicMock()
    ipa.word_to_ipa.return_value = "/a/"
    ipa.text_to_ipa.return_value = "/a/"
    scorer = MagicMock()
    scorer.mdd_threshold = 1.0
    svc = PronunciationV2Service(analyser=MagicMock(), scorer=scorer, ipa=ipa)
    a = V2Analysis([WordAnalysis("a", [PhoneAnalysis("a", "a", 0, 2, lpp=-0.1, features=np.zeros(43))])], [], 10)
    return svc._build_response("a", a, Scores([[1.9]], [9.0], {"accuracy": 9, "fluency": 9, "prosodic": 9, "total": 9}, 10.0))


@pytest.mark.asyncio
async def test_v2_evaluate_returns_v1_shape_plus_timing(app, client: AsyncClient, sample_audio_bytes):
    fake = MagicMock()
    fake.evaluate = AsyncMock(return_value=_v2_response())
    app.dependency_overrides[get_pronunciation_v2_svc] = lambda: fake
    resp = await client.post(
        "/api/v2/evaluate",
        data={"reference_text": "a"},
        files={"audio": ("t.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(PronunciationResponse.model_fields) <= set(body)
    word = body["results"]["word_details"][0]
    assert "start_ms" in word and "end_ms" in word
    fake.evaluate.assert_awaited_once()


@pytest.mark.asyncio
async def test_v2_rejects_same_bad_input_as_v1(client: AsyncClient):
    resp = await client.post(
        "/api/v2/evaluate",
        data={"reference_text": " "},
        files={"audio": ("t.wav", io.BytesIO(b"\x00" * 100), "audio/wav")},
    )
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_v2_unavailable_model_returns_503(app, client: AsyncClient, sample_audio_bytes, monkeypatch):
    import app.api.dependencies as deps

    def missing():
        raise FileNotFoundError("model.int8.onnx")

    monkeypatch.setattr(deps, "get_pronunciation_v2_service", missing)
    app.dependency_overrides.pop(get_pronunciation_v2_svc, None)
    resp = await client.post(
        "/api/v2/evaluate",
        data={"reference_text": "a"},
        files={"audio": ("t.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_v2_empty_model_dir_returns_503_without_mocking(app, client: AsyncClient, sample_audio_bytes, tmp_path, monkeypatch):
    """A real directory with no model files must degrade to 503, not crash (onnxruntime raises its own error type)."""
    from app.core.config import get_settings
    from app.services.v2.analyser import get_v2_analyser
    from app.services.v2.pronunciation_v2_service import get_pronunciation_v2_service

    monkeypatch.setenv("PHONE_MODEL_DIR", str(tmp_path))
    for cached in (get_settings, get_v2_analyser, get_pronunciation_v2_service):
        cached.cache_clear()
    app.dependency_overrides.pop(get_pronunciation_v2_svc, None)
    try:
        resp = await client.post(
            "/api/v2/evaluate",
            data={"reference_text": "a"},
            files={"audio": ("t.wav", io.BytesIO(sample_audio_bytes), "audio/wav")},
        )
        assert resp.status_code == 503
    finally:
        monkeypatch.undo()
        for cached in (get_settings, get_v2_analyser, get_pronunciation_v2_service):
            cached.cache_clear()
