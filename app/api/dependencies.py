"""API dependency injection."""
from __future__ import annotations

import hmac

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from loguru import logger

from app.core.config import get_settings
from app.services.pronunciation_service import PronunciationService, get_pronunciation_service
from app.services.v2.pronunciation_v2_service import PronunciationV2Service, get_pronunciation_v2_service

# ---------------------------------------------------------------------------
# API Key authentication
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Known weak / placeholder API key values that should never be used in
# production.  Compared case-insensitively.
_WEAK_API_KEYS: frozenset[str] = frozenset({
    "change-me-before-deploying",
    "change-me",
    "test",
    "secret",
    "password",
    "api-key",
    "your-api-key-here",
    "your-secret-api-key-here",
})


def warn_if_api_key_disabled() -> None:
    """Log a one-time warning when API key enforcement is disabled or weak.

    Called from the application lifespan at startup (not at import time) so
    that the log is emitted only after logging has been fully configured.
    """
    settings = get_settings()
    if not settings.api_key:
        logger.warning(
            "API key enforcement is DISABLED (API_KEY is not set). "
            "Set API_KEY in your .env or environment before deploying to production."
        )
    elif settings.api_key.lower() in _WEAK_API_KEYS:
        logger.warning(
            "API_KEY is set to a known weak/placeholder value '{}'. "
            "Generate a strong key before deploying: "
            "python -c \"import secrets; print(secrets.token_urlsafe(32))\"",
            settings.api_key,
        )


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> None:
    """Dependency that validates the X-API-Key header.

    - If ``settings.api_key`` is empty, enforcement is skipped (useful for
      local development without setting up a key).
    - Returns 401 when the header is missing entirely.
    - Returns 403 when the header is present but the value is wrong.
    """
    settings = get_settings()

    # No key configured → skip enforcement (warning already logged at startup)
    if not settings.api_key:
        return

    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Provide it via the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not hmac.compare_digest(api_key, settings.api_key):
        logger.warning("Rejected request with invalid API key.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )


async def get_pronunciation_svc() -> PronunciationService:
    """FastAPI dependency that returns the singleton PronunciationService."""
    return get_pronunciation_service()


async def get_pronunciation_v2_svc() -> PronunciationV2Service:
    """FastAPI dependency for the v2 service; 503 when the phone model files are absent."""
    try:
        return get_pronunciation_v2_service()
    except FileNotFoundError as exc:
        logger.error("v2 model files missing: {}", exc)
        raise HTTPException(status_code=503, detail="v2 model is not available on this server.")
