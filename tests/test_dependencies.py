"""Tests for API dependency injection (authentication)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.dependencies import verify_api_key

# ── verify_api_key ───────────────────────────────────────────────────────────


class TestVerifyApiKey:
    """Test the X-API-Key authentication dependency."""

    @patch("app.api.dependencies.get_settings")
    async def test_disabled_when_no_key_configured(self, mock_settings):
        """When API_KEY is empty, enforcement is skipped."""
        mock_settings.return_value = MagicMock(api_key="")
        # Should not raise — any value (even None) is accepted
        await verify_api_key(api_key=None)
        await verify_api_key(api_key="anything")

    @patch("app.api.dependencies.get_settings")
    async def test_401_when_header_missing(self, mock_settings):
        """When API_KEY is set but header is missing → 401."""
        mock_settings.return_value = MagicMock(api_key="secret-key")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key=None)
        assert exc_info.value.status_code == 401

    @patch("app.api.dependencies.get_settings")
    async def test_403_when_key_wrong(self, mock_settings):
        """When API_KEY is set but header has wrong value → 403."""
        mock_settings.return_value = MagicMock(api_key="secret-key")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key="wrong-key")
        assert exc_info.value.status_code == 403

    @patch("app.api.dependencies.get_settings")
    async def test_success_with_correct_key(self, mock_settings):
        """When API_KEY is set and header matches → passes silently."""
        mock_settings.return_value = MagicMock(api_key="secret-key")
        await verify_api_key(api_key="secret-key")  # no exception

    @patch("app.api.dependencies.get_settings")
    async def test_401_detail_message(self, mock_settings):
        """Check the error detail for 401."""
        mock_settings.return_value = MagicMock(api_key="secret-key")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key=None)
        assert "Missing API key" in exc_info.value.detail

    @patch("app.api.dependencies.get_settings")
    async def test_403_detail_message(self, mock_settings):
        """Check the error detail for 403."""
        mock_settings.return_value = MagicMock(api_key="secret-key")
        with pytest.raises(HTTPException) as exc_info:
            await verify_api_key(api_key="bad")
        assert "Invalid API key" in exc_info.value.detail
