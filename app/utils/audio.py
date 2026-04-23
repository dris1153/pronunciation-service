"""Audio I/O and pre-processing utilities."""
from __future__ import annotations

import io
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from loguru import logger

from app.core.config import get_settings

# ── Format detection helpers ─────────────────────────────────────────────────

# Magic bytes for formats that soundfile/librosa can read from BytesIO
# (container-based formats like WAV and FLAC).  MP3/OGG require file-based
# access via ffmpeg, so they still need a temp file.
_BYTESIO_MAGIC: list[tuple[bytes, str]] = [
    (b"RIFF", ".wav"),
    (b"fLaC", ".flac"),
]

# Magic bytes → file extension mapping for the temp-file fallback path.
# A correct extension helps ffmpeg identify the container format.
_MAGIC_TO_SUFFIX: list[tuple[bytes, str]] = [
    (b"RIFF", ".wav"),
    (b"fLaC", ".flac"),
    (b"OggS", ".ogg"),
    (b"ID3", ".mp3"),
    (b"\xff\xfb", ".mp3"),
    (b"\xff\xf3", ".mp3"),
    (b"\xff\xf2", ".mp3"),
    (b"\x1aE\xdf\xa3", ".webm"),
]

# Formats that soundfile (libsndfile) can decode natively without ffmpeg.
_SOUNDFILE_NATIVE_SUFFIXES = frozenset({".wav", ".flac"})


def _can_use_bytesio(data: bytes) -> str | None:
    """Return a suffix hint if the data can be loaded via BytesIO, else None."""
    for magic, suffix in _BYTESIO_MAGIC:
        if data[:len(magic)] == magic:
            return suffix
    return None


def _detect_suffix(data: bytes) -> str:
    """Return a file extension matching the audio container, or ``.audio``."""
    for magic, suffix in _MAGIC_TO_SUFFIX:
        if data[:len(magic)] == magic:
            return suffix
    return ".audio"


# ── ffmpeg resolution ────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _resolve_ffmpeg_path() -> str | None:
    """Find a working ``ffmpeg`` binary.

    Resolution order:
    1. ``ffmpeg`` on ``$PATH`` (system install / apt-get / brew).
    2. Bundled binary from ``imageio-ffmpeg`` (pip-installable, no system
       dependency required).

    Returns the absolute path to the binary, or ``None`` if unavailable.
    """
    # 1) System PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg is not None:
        try:
            subprocess.run(
                [system_ffmpeg, "-version"],
                capture_output=True,
                timeout=5,
            )
            return system_ffmpeg
        except (subprocess.SubprocessError, OSError):
            pass  # broken binary (e.g. DLL issues on Windows conda)

    # 2) imageio-ffmpeg bundled binary
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        pass

    return None


def _check_ffmpeg_available() -> bool:
    """Return ``True`` if a working ``ffmpeg`` binary can be found."""
    return _resolve_ffmpeg_path() is not None


def _ffmpeg_convert_to_wav(
    input_path: str,
    output_path: str,
    target_sr: int,
) -> None:
    """Convert *input_path* to 16-bit mono WAV at *target_sr* using ffmpeg.

    Raises ``RuntimeError`` if ffmpeg is unavailable or the conversion fails.
    """
    ffmpeg = _resolve_ffmpeg_path()
    if ffmpeg is None:
        raise RuntimeError(
            "Cannot decode audio: ffmpeg is not installed. "
            "Install it with 'pip install imageio-ffmpeg', "
            "'apt-get install ffmpeg', or 'brew install ffmpeg'."
        )

    cmd = [
        ffmpeg,
        "-y",                # overwrite output
        "-i", input_path,    # input file
        "-vn",               # no video
        "-ac", "1",          # mono
        "-ar", str(target_sr),  # target sample rate
        "-sample_fmt", "s16",   # 16-bit PCM
        "-f", "wav",         # output format
        output_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("ffmpeg conversion timed out (30s).") from exc

    if result.returncode != 0:
        stderr_tail = result.stderr[-500:].decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ffmpeg conversion failed (exit code {result.returncode}): {stderr_tail}"
        )


def load_audio_from_bytes(
    audio_bytes: bytes,
    target_sr: int | None = None,
) -> tuple[np.ndarray, int]:
    """Load audio from raw bytes and resample to *target_sr*.

    For WAV and FLAC formats, loading is done in-memory via ``io.BytesIO``
    to avoid filesystem I/O overhead.  Other formats (MP3, OGG, WebM) are
    converted to WAV via ``ffmpeg`` subprocess before loading with
    ``soundfile``.  This avoids the deprecated ``audioread`` fallback in
    librosa entirely.

    Returns
    -------
    waveform : np.ndarray  – 1-D float32 array
    sr       : int         – sample rate after resampling
    """
    settings = get_settings()
    target_sr = target_sr or settings.audio_sample_rate

    suffix = _can_use_bytesio(audio_bytes)
    if suffix is not None:
        # Fast path — in-memory loading for container formats
        buf = io.BytesIO(audio_bytes)
        waveform, sr = librosa.load(buf, sr=target_sr, mono=True)
        logger.debug("Loaded audio (BytesIO): duration={:.2f}s  sr={}", len(waveform) / sr, sr)
        return waveform, sr

    # Slow path — ffmpeg conversion for MP3, OGG, WebM, etc.
    suffix = _detect_suffix(audio_bytes)
    src_path: str | None = None
    wav_path: str | None = None
    try:
        # Write original bytes to a temp file with the correct extension
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            src_path = tmp.name

        # If soundfile can handle this format natively, use librosa directly
        if suffix in _SOUNDFILE_NATIVE_SUFFIXES:
            waveform, sr = librosa.load(src_path, sr=target_sr, mono=True)
            logger.debug(
                "Loaded audio (tmpfile/native): duration={:.2f}s  sr={}",
                len(waveform) / sr, sr,
            )
            return waveform, sr

        # Convert to WAV via ffmpeg
        wav_path = src_path + ".wav"
        _ffmpeg_convert_to_wav(src_path, wav_path, target_sr)

        # Load the converted WAV with soundfile (fast, no ffmpeg needed)
        data, sr = sf.read(wav_path, dtype="float32")
        waveform = data.astype(np.float32)
        # sf.read returns (samples,) for mono — already 1-D
        logger.debug(
            "Loaded audio (ffmpeg→WAV): duration={:.2f}s  sr={}",
            len(waveform) / sr, sr,
        )
        return waveform, sr
    finally:
        if src_path is not None:
            Path(src_path).unlink(missing_ok=True)
        if wav_path is not None:
            Path(wav_path).unlink(missing_ok=True)


def load_audio_from_path(
    path: str | Path,
    target_sr: int | None = None,
) -> tuple[np.ndarray, int]:
    """Load audio from a file path."""
    settings = get_settings()
    target_sr = target_sr or settings.audio_sample_rate
    waveform, sr = librosa.load(str(path), sr=target_sr, mono=True)
    return waveform, sr


def validate_audio_duration(waveform: np.ndarray, sr: int) -> None:
    """Raise ValueError if audio exceeds max allowed duration."""
    settings = get_settings()
    duration = len(waveform) / sr
    if duration > settings.audio_max_duration_sec:
        raise ValueError(
            f"Audio duration {duration:.1f}s exceeds maximum "
            f"of {settings.audio_max_duration_sec}s."
        )


def normalize_audio(waveform: np.ndarray) -> np.ndarray:
    """Peak-normalise waveform to [-1, 1].

    .. important::

       Always call ``is_silent(waveform)`` **before** this function.
       After peak-normalisation every non-zero signal has RMS ≈ 0.7,
       making a subsequent ``is_silent()`` check ineffective.
    """
    peak = np.max(np.abs(waveform))
    if peak > 0:
        waveform = waveform / peak
    return waveform


def is_silent(waveform: np.ndarray, threshold: float = 0.01) -> bool:
    """Return ``True`` if the waveform RMS energy is below *threshold*.

    A typical threshold of **0.01** (i.e. 1 % of full-scale) reliably
    identifies recordings that contain only background noise or silence.
    Callers should skip expensive ML inference (ASR, GOP) when this
    returns ``True`` and surface an appropriate error to the user instead.

    Parameters
    ----------
    waveform:
        1-D float32 numpy array (any sample rate).
    threshold:
        RMS energy threshold.  Default 0.01 works for 16-bit-equivalent
        float audio in the range [-1, 1].
    """
    rms = float(np.sqrt(np.mean(waveform ** 2)))
    return rms < threshold


# ── Magic-bytes content-type detection ───────────────────────────────────────

# Mapping of (offset, magic_bytes) → MIME type for supported audio formats.
_MAGIC_SIGNATURES: list[tuple[int, bytes, str]] = [
    (0, b"RIFF", "audio/wav"),        # WAV / WAVE
    (0, b"fLaC", "audio/flac"),       # FLAC
    (0, b"OggS", "audio/ogg"),        # OGG
    (0, b"ID3", "audio/mpeg"),         # MP3 with ID3 tag
    (0, b"\xff\xfb", "audio/mpeg"),   # MP3 frame sync (MPEG1 Layer3)
    (0, b"\xff\xf3", "audio/mpeg"),   # MP3 frame sync (MPEG1 Layer3 variant)
    (0, b"\xff\xf2", "audio/mpeg"),   # MP3 frame sync (MPEG2 Layer3)
    (0, b"\x1aE\xdf\xa3", "audio/webm"),  # WebM / MKV
]


def detect_audio_mime_type(data: bytes) -> str | None:
    """Detect audio MIME type from the first few bytes (magic bytes).

    Returns the MIME type string if recognised, or ``None`` if unknown.

    Parameters
    ----------
    data:
        Raw audio bytes (at least 12 bytes recommended for reliable detection).
    """
    for offset, magic, mime in _MAGIC_SIGNATURES:
        end = offset + len(magic)
        if len(data) >= end and data[offset:end] == magic:
            return mime
    return None
