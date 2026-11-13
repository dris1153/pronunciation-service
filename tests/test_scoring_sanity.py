"""Pytest regression suite over the 5-recording sanity dataset (Phase 06).

Skipped automatically until ``scripts/generate_sanity_audio.py`` has been run
and the dataset directories exist. The baseline JSON is compared by
``scripts/sanity_eval.py``; this test only enforces the band defined in
each recording's ``expected.json``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

DATASET = Path(__file__).parent / "sanity_dataset"


def _recording_dirs() -> list[Path]:
    if not DATASET.exists():
        return []
    return [p for p in sorted(DATASET.iterdir()) if p.is_dir()]


_RECORDING_DIRS = _recording_dirs()


@pytest.mark.skipif(
    not _RECORDING_DIRS,
    reason="Sanity dataset not generated. Run scripts/generate_sanity_audio.py.",
)
@pytest.mark.parametrize(
    "recording_dir", _RECORDING_DIRS, ids=lambda p: p.name
)
@pytest.mark.asyncio
async def test_recording_within_band(recording_dir: Path, client):
    audio = (recording_dir / "audio.wav").read_bytes()
    ref = (recording_dir / "reference.txt").read_text(encoding="utf-8").strip()
    expected = json.loads(
        (recording_dir / "expected.json").read_text(encoding="utf-8")
    )

    response = await client.post(
        "/api/v1/evaluate",
        files={"audio": ("a.wav", audio, "audio/wav")},
        data={"reference_text": ref},
    )
    assert response.status_code == 200, response.text
    score = response.json()["overall_score"]
    lo, hi = expected["min_score"], expected["max_score"]
    assert lo <= score <= hi, (
        f"{recording_dir.name}: score={score:.1f}, expected [{lo}, {hi}]"
    )


def _v2_model_available() -> bool:
    from app.core.config import get_settings

    s = get_settings()
    onnx = "model.int8.onnx" if s.phone_model_int8 else "model.onnx"
    return all((Path(s.phone_model_dir) / f).exists() for f in (onnx, "vocab.json", "scorer.json"))


@pytest.mark.skipif(
    not _RECORDING_DIRS or not _v2_model_available(),
    reason="Sanity dataset or v2 model files not available.",
)
@pytest.mark.parametrize("recording_dir", _RECORDING_DIRS, ids=lambda p: p.name)
def test_recording_within_band_v2(recording_dir: Path):
    from app.services.v2.pronunciation_v2_service import get_pronunciation_v2_service

    audio = (recording_dir / "audio.wav").read_bytes()
    ref = (recording_dir / "reference.txt").read_text(encoding="utf-8").strip()
    expected = json.loads((recording_dir / "expected.json").read_text(encoding="utf-8"))

    score = get_pronunciation_v2_service()._evaluate_sync(audio, ref).overall_score
    lo, hi = expected["min_score"], expected["max_score"]
    assert lo <= score <= hi, f"{recording_dir.name}: v2 score={score:.1f}, expected [{lo}, {hi}]"
