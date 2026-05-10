"""Async ffprobe pre-decode duration check (Phase 02 / Finding 11)."""
from __future__ import annotations

import io

import numpy as np
import pytest
import soundfile as sf

from app.utils.audio import (
    _DEMUXER_BY_MIME,
    _duration_from_soundfile_bytes,
    precheck_audio_duration,
)


def _make_wav(duration_sec: float, sr: int = 16000) -> bytes:
    n = int(duration_sec * sr)
    waveform = np.zeros(n, dtype=np.float32)
    buf = io.BytesIO()
    sf.write(buf, waveform, sr, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def test_demuxer_map_covers_all_supported_mimes():
    expected = {
        "audio/wav", "audio/x-wav", "audio/wave",
        "audio/flac", "audio/mpeg", "audio/mp3",
        "audio/ogg", "audio/webm",
    }
    assert expected.issubset(_DEMUXER_BY_MIME.keys())


def test_inmemory_duration_for_wav():
    wav = _make_wav(2.5)
    assert _duration_from_soundfile_bytes(wav) == pytest.approx(2.5, rel=0.01)


@pytest.mark.asyncio
async def test_precheck_passes_short_wav():
    wav = _make_wav(2.0)
    duration = await precheck_audio_duration(wav, "audio/wav", max_duration_sec=30.0)
    assert duration == pytest.approx(2.0, rel=0.01)


@pytest.mark.asyncio
async def test_precheck_rejects_long_wav():
    # 35s > 30s default max
    wav = _make_wav(35.0)
    with pytest.raises(ValueError, match="exceeds maximum"):
        await precheck_audio_duration(wav, "audio/wav", max_duration_sec=30.0)


@pytest.mark.asyncio
async def test_precheck_unsupported_mime_raises():
    wav = _make_wav(1.0)
    with pytest.raises(ValueError):
        await precheck_audio_duration(wav, "application/octet-stream", 30.0)
