"""Tests for audio utility functions."""
from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import soundfile as sf

# ── normalize_audio ──────────────────────────────────────────────────────────


class TestNormalizeAudio:
    """Test peak normalisation."""

    def test_normalises_to_unit_peak(self):
        from app.utils.audio import normalize_audio

        waveform = np.array([0.0, 0.5, -1.0, 0.25], dtype=np.float32)
        result = normalize_audio(waveform)
        assert np.isclose(np.max(np.abs(result)), 1.0)

    def test_already_normalised(self):
        from app.utils.audio import normalize_audio

        waveform = np.array([0.0, 1.0, -1.0, 0.5], dtype=np.float32)
        result = normalize_audio(waveform)
        np.testing.assert_array_almost_equal(result, waveform)

    def test_silent_audio_unchanged(self):
        from app.utils.audio import normalize_audio

        waveform = np.zeros(100, dtype=np.float32)
        result = normalize_audio(waveform)
        np.testing.assert_array_equal(result, waveform)

    def test_loud_audio_scaled_down(self):
        from app.utils.audio import normalize_audio

        waveform = np.array([2.0, -4.0, 1.0], dtype=np.float32)
        result = normalize_audio(waveform)
        assert np.max(np.abs(result)) <= 1.0 + 1e-7
        # Peak should be at element index 1 (value -4.0 → -1.0)
        assert np.isclose(result[1], -1.0)

    def test_single_sample(self):
        from app.utils.audio import normalize_audio

        waveform = np.array([0.3], dtype=np.float32)
        result = normalize_audio(waveform)
        assert np.isclose(result[0], 1.0)


# ── validate_audio_duration ──────────────────────────────────────────────────


class TestValidateAudioDuration:
    """Test duration limit enforcement."""

    @patch("app.utils.audio.get_settings")
    def test_short_audio_passes(self, mock_settings):
        from app.utils.audio import validate_audio_duration

        mock_settings.return_value = MagicMock(audio_max_duration_sec=30)
        waveform = np.zeros(16000 * 10, dtype=np.float32)  # 10 seconds
        validate_audio_duration(waveform, 16000)  # should not raise

    @patch("app.utils.audio.get_settings")
    def test_exactly_at_limit_passes(self, mock_settings):
        from app.utils.audio import validate_audio_duration

        mock_settings.return_value = MagicMock(audio_max_duration_sec=30)
        waveform = np.zeros(16000 * 30, dtype=np.float32)  # exactly 30s
        validate_audio_duration(waveform, 16000)  # should not raise

    @patch("app.utils.audio.get_settings")
    def test_too_long_raises_value_error(self, mock_settings):
        from app.utils.audio import validate_audio_duration

        mock_settings.return_value = MagicMock(audio_max_duration_sec=30)
        waveform = np.zeros(16000 * 31, dtype=np.float32)  # 31 seconds
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_audio_duration(waveform, 16000)

    @patch("app.utils.audio.get_settings")
    def test_custom_limit(self, mock_settings):
        from app.utils.audio import validate_audio_duration

        mock_settings.return_value = MagicMock(audio_max_duration_sec=5)
        waveform = np.zeros(16000 * 6, dtype=np.float32)  # 6s > 5s
        with pytest.raises(ValueError):
            validate_audio_duration(waveform, 16000)


# ── load_audio_from_bytes ────────────────────────────────────────────────────


class TestLoadAudioFromBytes:
    """Test loading audio from byte buffers."""

    @patch("app.utils.audio.get_settings")
    def test_loads_wav_bytes(self, mock_settings):
        from app.utils.audio import load_audio_from_bytes

        mock_settings.return_value = MagicMock(audio_sample_rate=16000)

        # Create real WAV bytes
        sr = 16000
        duration = 0.5
        t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
        audio_data = np.sin(2 * np.pi * 440 * t)

        buf = io.BytesIO()
        sf.write(buf, audio_data, sr, format="WAV")
        wav_bytes = buf.getvalue()

        waveform, out_sr = load_audio_from_bytes(wav_bytes)
        assert out_sr == 16000
        assert isinstance(waveform, np.ndarray)
        assert len(waveform) > 0

    @patch("app.utils.audio.get_settings")
    def test_output_is_mono_float32(self, mock_settings):
        from app.utils.audio import load_audio_from_bytes

        mock_settings.return_value = MagicMock(audio_sample_rate=16000)

        sr = 16000
        audio_data = np.random.randn(sr).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, audio_data, sr, format="WAV")

        waveform, _ = load_audio_from_bytes(buf.getvalue())
        assert waveform.ndim == 1  # mono
        assert waveform.dtype == np.float32

    @patch("app.utils.audio.get_settings")
    def test_custom_target_sr(self, mock_settings):
        from app.utils.audio import load_audio_from_bytes

        mock_settings.return_value = MagicMock(audio_sample_rate=16000)

        sr = 44100
        audio_data = np.random.randn(sr).astype(np.float32)
        buf = io.BytesIO()
        sf.write(buf, audio_data, sr, format="WAV")

        waveform, out_sr = load_audio_from_bytes(buf.getvalue(), target_sr=8000)
        assert out_sr == 8000


# ── is_silent ────────────────────────────────────────────────────────────────


class TestIsSilent:
    """Test RMS-energy silence detection."""

    def test_zero_waveform_is_silent(self):
        from app.utils.audio import is_silent

        waveform = np.zeros(16000, dtype=np.float32)
        assert is_silent(waveform) is True

    def test_loud_waveform_not_silent(self):
        from app.utils.audio import is_silent

        waveform = np.ones(16000, dtype=np.float32) * 0.5
        assert is_silent(waveform) is False

    def test_noise_above_threshold_not_silent(self):
        from app.utils.audio import is_silent

        # RNG seed for reproducibility; np.random.randn gives RMS ≈ 1.0
        rng = np.random.default_rng(42)
        waveform = rng.standard_normal(16000).astype(np.float32)
        assert is_silent(waveform) is False

    def test_very_quiet_signal_is_silent(self):
        from app.utils.audio import is_silent

        # RMS = 0.001 — well below default threshold of 0.01
        waveform = np.full(16000, 0.001, dtype=np.float32)
        assert is_silent(waveform) is True

    def test_custom_threshold(self):
        from app.utils.audio import is_silent

        waveform = np.full(16000, 0.05, dtype=np.float32)
        # With default threshold (0.01) this is NOT silent
        assert is_silent(waveform, threshold=0.01) is False
        # With a higher threshold (0.1) the same signal IS silent
        assert is_silent(waveform, threshold=0.1) is True

    def test_single_sample(self):
        from app.utils.audio import is_silent

        assert is_silent(np.array([0.0], dtype=np.float32)) is True
        assert is_silent(np.array([1.0], dtype=np.float32)) is False
