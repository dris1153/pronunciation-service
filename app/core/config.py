"""Core configuration and settings."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
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
    # v2 phone CTC model: directory with model.onnx + vocab.json
    phone_model_dir: str = "./data/models/hubert-phone-ctc"

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

    # Rate limiting (Phase 01 / Finding 4 + Per-User Redesign)
    rate_limit_enabled: bool = True
    # Per-key per-minute caps. Key = IP (default) OR end-user-id when called
    # from a trusted backend with X-Service-Auth set (see service_api_key).
    rate_limit_evaluate_per_minute: int = 20
    rate_limit_transcribe_per_minute: int = 15
    rate_limit_text_analysis_per_minute: int = 120

    # Service-to-service auth key (Per-User Rate Limit Redesign).
    # When set, callers from a trusted-proxy CIDR can pass:
    #   X-Service-Auth: <this value>
    #   X-End-User-Id: <user-uuid|anon-session_id>
    # to be rate-limited per-end-user instead of per-IP.
    # Empty (default) = feature disabled, all callers key by IP.
    # Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
    service_api_key: str = ""

    # Per-request timeout (Phase 01)
    request_timeout_sec: int = 90

    # CIDRs to trust as reverse-proxy peers when parsing X-Forwarded-For.
    # Default = Docker RFC1918 ranges (Coolify Traefik). Operator can narrow
    # to a specific Coolify proxy container IP via:
    #   docker network inspect coolify
    trusted_proxy_cidrs_str: str = "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"

    @property
    def trusted_proxy_cidrs(self) -> list[str]:
        return [c.strip() for c in self.trusted_proxy_cidrs_str.split(",") if c.strip()]

    # ── Concurrency ──────────────────────────────────────────
    # 0 = auto-detect via cgroup-aware sched_getaffinity (Phase 02 / Finding 2).
    # Positive value = explicit override.
    max_concurrent_inferences: int = 0

    # Queue timeout: requests waiting > this many seconds → 503 Retry-After.
    inference_queue_timeout_sec: float = 60.0

    # ── ASR backend (Phase 03 / Finding 1) ───────────────────
    # Default = torch_fp32 until P06 sanity gate confirms torch_int8 safe.
    inference_backend: Literal["torch_fp32", "torch_int8"] = "torch_fp32"

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

    # ── Validators ───────────────────────────────────────────

    @model_validator(mode="after")
    def _enforce_api_key_in_prod(self) -> "Settings":
        """Block startup in prod if API_KEY is missing, weak, or too short.

        Skipped when DEBUG=True (dev convenience). Reuses the weak-key set
        defined in app.api.dependencies (imported lazily to avoid cycle).
        """
        if self.debug:
            return self
        # Lazy import to break circular dependency at import time.
        from app.api.dependencies import _WEAK_API_KEYS

        if not self.api_key:
            raise ValueError("API_KEY must be set when DEBUG=False.")
        if self.api_key.lower() in _WEAK_API_KEYS:
            raise ValueError(
                "API_KEY value rejected (matches known-weak placeholder list). "
                'Generate a strong key: python -c "import secrets; '
                'print(secrets.token_urlsafe(32))"'
            )
        if len(self.api_key) < 32:
            raise ValueError(
                "API_KEY must be at least 32 characters when DEBUG=False."
            )
        return self


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
