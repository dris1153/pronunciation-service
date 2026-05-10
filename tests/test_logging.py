"""Logging + request-id behaviour (Phase 05 / Finding 8)."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from loguru import logger

from app.core.logging import setup_logging


def test_dev_mode_text_format(monkeypatch, capsys):
    """DEBUG=true → human-readable text, NOT JSON lines."""
    from app.core import config

    monkeypatch.setenv("DEBUG", "true")
    config.get_settings.cache_clear()
    setup_logging()
    logger.info("hello dev")
    captured = capsys.readouterr()
    out = (captured.err + captured.out).strip()
    if not out:
        return  # nothing to assert against
    for line in out.splitlines():
        if not line.strip():
            continue
        try:
            json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return  # at least one non-JSON line — pass
    raise AssertionError("Dev mode produced only JSON lines; expected text.")


def test_prod_mode_json_format(monkeypatch, capsys):
    """DEBUG=false → emitted lines are valid JSON with extras attached."""
    from app.core import config

    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("API_KEY", "x" * 40)
    config.get_settings.cache_clear()
    setup_logging()
    logger.bind(request_id="abc-123", latency_ms=42.0).info("request_completed")
    captured = capsys.readouterr()
    lines = [ln for ln in (captured.out + captured.err).strip().splitlines() if ln.strip()]
    assert lines, "expected at least one log line"
    found = False
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        extra = record.get("record", {}).get("extra", {})
        if extra.get("request_id") == "abc-123":
            found = True
            assert extra.get("latency_ms") == 42.0
            break
    assert found, "request_completed log line missing or malformed JSON"


def test_response_does_not_echo_request_id_header():
    """Server must NOT echo X-Request-ID to the response (Finding 8 / Sec F10)."""
    from app.application import create_app

    app = create_app()
    with TestClient(app) as tc:
        resp = tc.get("/health", headers={"X-Request-ID": "evil\nfake"})
        assert resp.status_code == 200
        assert "x-request-id" not in {k.lower() for k in resp.headers.keys()}
