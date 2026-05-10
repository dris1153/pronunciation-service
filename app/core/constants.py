"""Shared application constants."""
from __future__ import annotations

# ── Audio upload constraints ─────────────────────────────────────────────────

MAX_UPLOAD_MB: int = 10  # blanket cap across all formats (Phase 02 / Finding 13)
MAX_UPLOAD_BYTES: int = MAX_UPLOAD_MB * 1024 * 1024

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

# ── Reference text validation (Phase 01 / Finding 10) ───────────────────────
MAX_REFERENCE_TEXT_LENGTH: int = 500
MAX_REFERENCE_WORD_COUNT: int = 100
MAX_WORD_LENGTH: int = 30

# ── Concurrency cap (Phase 02 / Finding 2) ──────────────────────────────────
MAX_CONCURRENT_INFERENCES_CAP: int = 4

# ── ffprobe pre-decode timeout (Phase 02 / Finding 11) ──────────────────────
FFPROBE_TIMEOUT_SEC: int = 2
