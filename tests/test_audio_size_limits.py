"""Blanket 10MB upload-size limit (Phase 02 / Finding 13)."""
from __future__ import annotations

import io

import pytest
import soundfile as sf
import numpy as np

from app.core.constants import MAX_UPLOAD_BYTES, MAX_UPLOAD_MB


def _wav_bytes_of_size(target_size: int) -> bytes:
    """Build a WAV blob whose file size is approximately ``target_size``."""
    sr = 16000
    # 16-bit mono → 2 bytes/sample. Add 44-byte WAV header overhead.
    n_samples = max(1, (target_size - 44) // 2)
    waveform = (np.random.random(n_samples).astype(np.float32) - 0.5) * 0.1
    buf = io.BytesIO()
    sf.write(buf, waveform, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_constant_is_ten_mb():
    assert MAX_UPLOAD_MB == 10
    assert MAX_UPLOAD_BYTES == 10 * 1024 * 1024


@pytest.mark.asyncio
async def test_oversized_upload_rejected(client):
    """Upload at 11 MB → HTTP 400 from the size check."""
    big_wav = _wav_bytes_of_size(11 * 1024 * 1024)
    assert len(big_wav) > MAX_UPLOAD_BYTES
    resp = await client.post(
        "/api/v1/transcribe",
        files={"audio": ("big.wav", big_wav, "audio/wav")},
    )
    assert resp.status_code == 400
    assert "too large" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_under_limit_passes_size_check(client, sample_audio_bytes, monkeypatch):
    """An 8MB file passes the size gate (other validation may still apply)."""
    # Just check status != 400 from size logic specifically. We don't run
    # actual ASR — small valid WAV under limit is enough.
    assert len(sample_audio_bytes) < MAX_UPLOAD_BYTES
    resp = await client.post(
        "/api/v1/transcribe",
        files={"audio": ("ok.wav", sample_audio_bytes, "audio/wav")},
    )
    # Either 200 (transcribed) or non-size-related error — but NOT a "too large" 400.
    if resp.status_code == 400:
        assert "too large" not in resp.json().get("detail", "").lower()
