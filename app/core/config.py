"""Core configuration and settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to project root (two levels up from this file)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────
    app_name: str = "Pronunciation Validator"
    app_version: str = "1.0.0"
    app_host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # ── Model ────────────────────────────────────────────────
    asr_model_name: str = "facebook/wav2vec2-base-960h"
    asr_model_cache_dir: str = "./model_cache"
    device: str = "cpu"  # "cpu" | "cuda"

    # ── Audio ────────────────────────────────────────────────
    audio_sample_rate: int = 16000
    audio_max_duration_sec: int = 30

    # ── Prosody ──────────────────────────────────────────────
    prosody_pitch_min_hz: float = 65.0    # pyin fmin — ~C2
    prosody_pitch_max_hz: float = 600.0   # pyin fmax — covers high female voice
    prosody_monotone_threshold: float = 0.08  # Pitch CV below this → monotone
    # Upper CV bound for variance scoring: CV >= this value → score 100.
    # Must be strictly greater than prosody_monotone_threshold (validated at startup).
    # Native speakers typically have CV 0.15–0.30; non-native often < 0.12.
    prosody_pitch_cv_upper: float = 0.25

    # ── Security ─────────────────────────────────────────────
    # Set a non-empty string to require X-API-Key header on protected endpoints.
    # Leave empty ("") to disable API key enforcement (not recommended in production).
    api_key: str = ""

    # ── Concurrency ──────────────────────────────────────────
    # Maximum number of ML inference jobs (evaluate / transcribe) that may run
    # concurrently.  Additional requests are queued, not rejected.
    # Recommended: 2 for Railway (1 active + 1 warming up).
    max_concurrent_inferences: int = 2

    # ── CORS ─────────────────────────────────────────────────
    # Comma-separated list of allowed origins, e.g.:
    #   CORS_ORIGINS=https://app.example.com,https://admin.example.com
    # Leave as * (or unset) to allow all origins (development only).
    # Stored as a raw string; access via the `cors_origins` property below.
    cors_origins_str: str = "*"

    @property
    def cors_origins(self) -> list[str]:
        """Parse CORS_ORIGINS_STR into a list.

        Accepts a plain comma-separated string (``*``,
        ``https://a.com,https://b.com``) or a JSON array
        (``["https://a.com","https://b.com"]``).
        """
        v = self.cors_origins_str.strip()
        if v.startswith("["):
            import json
            return json.loads(v)
        return [origin.strip() for origin in v.split(",") if origin.strip()]

    # ── Logging ──────────────────────────────────────────────
    log_level: str = "INFO"

    @property
    def model_cache_path(self) -> Path:
        return Path(self.asr_model_cache_dir)


@lru_cache
def get_settings() -> Settings:
    """Cached singleton for settings."""
    settings = Settings()
    # Log resolved .env path on first load for easier debugging
    from loguru import logger
    logger.debug(".env path resolved to: {}", _ENV_FILE)
    logger.debug(
        "ASR model: {}  |  device: {}  |  port: {}",
        settings.asr_model_name, settings.device, settings.port,
    )
    return settings
