"""Worker-count guard at module-import time (Phase 02 / Finding 3)."""
from __future__ import annotations

import sys

import pytest

from app.application import _detect_worker_count


def test_default_no_env_no_argv_returns_one(monkeypatch):
    for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", ["python", "main.py"])
    assert _detect_worker_count() == 1


def test_web_concurrency_env_detected(monkeypatch):
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)
    monkeypatch.delenv("GUNICORN_WORKERS", raising=False)
    monkeypatch.setattr(sys, "argv", ["python"])
    assert _detect_worker_count() == 4


def test_workers_argv_long_form_detected(monkeypatch):
    for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", ["uvicorn", "app:app", "--workers", "3"])
    assert _detect_worker_count() == 3


def test_workers_argv_short_form_detected(monkeypatch):
    for var in ("WEB_CONCURRENCY", "UVICORN_WORKERS", "GUNICORN_WORKERS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "argv", ["gunicorn", "-w", "2", "app:app"])
    assert _detect_worker_count() == 2


def test_max_across_sources(monkeypatch):
    """If multiple sources are set, the highest count wins (most defensive)."""
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    monkeypatch.setenv("GUNICORN_WORKERS", "5")
    monkeypatch.setattr(sys, "argv", ["python"])
    assert _detect_worker_count() == 5
