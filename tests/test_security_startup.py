"""Settings validator tests — fail-fast on missing/weak/short API_KEY in prod.

Phase 01 / Finding 9.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _make(**overrides) -> Settings:
    """Construct Settings without reading .env (skip user's local file)."""
    # `_env_file=None` disables .env loading so we test pure overrides.
    return Settings(_env_file=None, **overrides)


def test_prod_empty_api_key_rejected():
    with pytest.raises(ValidationError) as exc:
        _make(debug=False, api_key="")
    assert "API_KEY must be set" in str(exc.value)


def test_prod_weak_api_key_rejected():
    with pytest.raises(ValidationError) as exc:
        _make(debug=False, api_key="change-me")
    assert "weak" in str(exc.value).lower()


def test_prod_short_api_key_rejected():
    with pytest.raises(ValidationError) as exc:
        _make(debug=False, api_key="short")
    assert "32 characters" in str(exc.value)


def test_prod_strong_api_key_accepted():
    s = _make(debug=False, api_key="x" * 32)
    assert s.api_key == "x" * 32


def test_dev_mode_skips_strength_check():
    # In DEBUG mode, even an empty key is allowed (developer convenience).
    s = _make(debug=True, api_key="")
    assert s.debug is True
    assert s.api_key == ""
