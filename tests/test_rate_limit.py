"""Rate-limit keying tests — Phase 01 (XFF-aware) + Per-User Redesign.

These tests focus on the keying logic. Full HTTP integration tests are
covered by test_api.py with rate limit disabled via the conftest fixture.
"""
from __future__ import annotations

import ipaddress
from unittest.mock import MagicMock

from app.api.middleware import (
    _client_ip_key,
    _is_trusted_peer,
    _parse_trusted_nets,
    _validate_user_id,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


_VALID_SVC_KEY = "test-svc-key-32chars-long-xxxxxx"


def _mock_request(peer: str, xff: str | None = None, headers: dict | None = None):
    request = MagicMock()
    request.client = MagicMock(host=peer)
    h = {}
    if xff is not None:
        h["x-forwarded-for"] = xff
    if headers:
        h.update(headers)
    request.headers = h
    return request


def _mock_settings(
    monkeypatch,
    *,
    cidrs: list[str] | None = None,
    service_key: str = "",
):
    """Patch app.api.middleware.get_settings + reset config singleton cache."""
    from app.core import config as config_mod

    config_mod.get_settings.cache_clear()
    settings_obj = type(
        "S",
        (),
        {
            "trusted_proxy_cidrs": cidrs or ["172.16.0.0/12"],
            "service_api_key": service_key,
        },
    )()
    monkeypatch.setattr("app.api.middleware.get_settings", lambda: settings_obj)


# ── _parse_trusted_nets ─────────────────────────────────────────────────────


def test_parse_trusted_nets_filters_invalid():
    nets = _parse_trusted_nets(["10.0.0.0/8", "not-a-cidr", "172.16.0.0/12"])
    assert len(nets) == 2
    assert ipaddress.ip_address("10.1.2.3") in nets[0]


# ── _is_trusted_peer ────────────────────────────────────────────────────────


def test_is_trusted_peer_inside_cidr(monkeypatch):
    _mock_settings(monkeypatch, cidrs=["172.16.0.0/12"])
    assert _is_trusted_peer("172.17.0.5") is True


def test_is_trusted_peer_outside_cidr(monkeypatch):
    _mock_settings(monkeypatch, cidrs=["172.16.0.0/12"])
    assert _is_trusted_peer("8.8.8.8") is False


def test_is_trusted_peer_invalid_ip(monkeypatch):
    _mock_settings(monkeypatch, cidrs=["172.16.0.0/12"])
    assert _is_trusted_peer("not-an-ip") is False


# ── _validate_user_id ───────────────────────────────────────────────────────


def test_validate_user_id_accepts_uuid():
    assert _validate_user_id("u_abc123") == "u_abc123"
    assert _validate_user_id("anon-550e8400-e29b-41d4-a716-446655440000") is not None


def test_validate_user_id_strips_whitespace():
    assert _validate_user_id("  u_abc  ") == "u_abc"


def test_validate_user_id_rejects_empty():
    assert _validate_user_id("") is None
    assert _validate_user_id("   ") is None


def test_validate_user_id_rejects_control_chars():
    assert _validate_user_id("evil\nuser") is None
    assert _validate_user_id("u\x00null") is None
    assert _validate_user_id("a\tb") is None


def test_validate_user_id_rejects_overlong():
    assert _validate_user_id("x" * 129) is None
    assert _validate_user_id("x" * 128) is not None


# ── _client_ip_key — XFF behaviour (existing semantics, namespaced keys) ────


def test_untrusted_peer_xff_ignored(monkeypatch):
    """XFF from a non-proxy peer must NOT be honoured."""
    _mock_settings(monkeypatch)
    request = _mock_request(peer="8.8.8.8", xff="1.2.3.4")
    assert _client_ip_key(request) == "ip:8.8.8.8"


def test_trusted_peer_xff_honoured(monkeypatch):
    _mock_settings(monkeypatch)
    request = _mock_request(peer="172.17.0.5", xff="1.2.3.4")
    assert _client_ip_key(request) == "ip:1.2.3.4"


def test_trusted_peer_no_xff_uses_peer(monkeypatch):
    _mock_settings(monkeypatch)
    request = _mock_request(peer="172.17.0.5")
    assert _client_ip_key(request) == "ip:172.17.0.5"


def test_xff_takes_first_ip(monkeypatch):
    """XFF chain must use the leftmost IP (closest to original client)."""
    _mock_settings(monkeypatch)
    request = _mock_request(peer="172.17.0.5", xff="1.2.3.4, 5.6.7.8, 9.10.11.12")
    assert _client_ip_key(request) == "ip:1.2.3.4"


# ── _client_ip_key — 4-branch decision table (Per-User Redesign) ────────────


def test_branch_untrusted_peer_keys_by_ip(monkeypatch):
    """Even with valid service auth + user_id, untrusted peer keys by IP.

    This is the spoof-prevention test: an attacker on 8.8.8.8 sending the
    real service key + a victim's user_id must NOT be able to consume the
    victim's quota.
    """
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="8.8.8.8",
        headers={"x-service-auth": _VALID_SVC_KEY, "x-end-user-id": "u_victim"},
    )
    assert _client_ip_key(request) == "ip:8.8.8.8"


def test_branch_trusted_no_service_auth_keys_by_ip(monkeypatch):
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="172.17.0.5",
        headers={"x-end-user-id": "u_abc"},
    )
    assert _client_ip_key(request) == "ip:172.17.0.5"


def test_branch_trusted_wrong_service_auth_keys_by_ip(monkeypatch):
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="172.17.0.5",
        headers={"x-service-auth": "wrong", "x-end-user-id": "u_abc"},
    )
    assert _client_ip_key(request) == "ip:172.17.0.5"


def test_branch_trusted_auth_no_user_id_keys_by_ip(monkeypatch):
    """Product BE bug fallback: missing X-End-User-Id → key by IP, not crash."""
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="172.17.0.5",
        headers={"x-service-auth": _VALID_SVC_KEY},
    )
    assert _client_ip_key(request) == "ip:172.17.0.5"


def test_branch_trusted_auth_invalid_user_id_keys_by_ip(monkeypatch):
    """Malformed user_id (control chars) → fallback to IP key."""
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="172.17.0.5",
        headers={"x-service-auth": _VALID_SVC_KEY, "x-end-user-id": "evil\nuser"},
    )
    assert _client_ip_key(request) == "ip:172.17.0.5"


def test_branch_trusted_auth_with_user_id_keys_by_user(monkeypatch):
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="172.17.0.5",
        headers={"x-service-auth": _VALID_SVC_KEY, "x-end-user-id": "u_abc"},
    )
    assert _client_ip_key(request) == "user:u_abc"


def test_service_key_disabled_means_ip_only(monkeypatch):
    """When service_api_key='' (default), feature is OFF — always key by IP.

    Backward compatibility check: existing deployments that don't set
    SERVICE_API_KEY behave identically to pre-redesign behaviour.
    """
    _mock_settings(monkeypatch, service_key="")
    request = _mock_request(
        peer="172.17.0.5",
        headers={"x-service-auth": "anything", "x-end-user-id": "u_abc"},
    )
    assert _client_ip_key(request) == "ip:172.17.0.5"


def test_anonymous_user_id_pattern(monkeypatch):
    """anon-<session_id> pattern produces per-session quota."""
    _mock_settings(monkeypatch, service_key=_VALID_SVC_KEY)
    request = _mock_request(
        peer="172.17.0.5",
        headers={
            "x-service-auth": _VALID_SVC_KEY,
            "x-end-user-id": "anon-550e8400-e29b-41d4-a716-446655440000",
        },
    )
    assert _client_ip_key(request) == "user:anon-550e8400-e29b-41d4-a716-446655440000"
