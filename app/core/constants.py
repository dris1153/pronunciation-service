"""Shared application constants."""
from __future__ import annotations

# ── Audio upload constraints ─────────────────────────────────────────────────

MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024  # 25 MB
MAX_UPLOAD_MB: int = 25

# Supported audio MIME types — single source of truth used by route
# validation AND the /model-info endpoint.
ALLOWED_AUDIO_TYPES: set[str] = {
    "audio/flac",
    "audio/mp3",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/wave",
    "audio/webm",
    "audio/x-wav",
}

# Sorted list variant for API responses (deterministic order).
SUPPORTED_AUDIO_FORMATS: list[str] = sorted(ALLOWED_AUDIO_TYPES)
