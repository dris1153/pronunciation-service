"""ASR backend selection tests (Phase 03)."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_backend_is_torch_fp32():
    s = Settings(_env_file=None, debug=True)
    assert s.inference_backend == "torch_fp32"


def test_torch_int8_accepted():
    s = Settings(_env_file=None, debug=True, inference_backend="torch_int8")
    assert s.inference_backend == "torch_int8"


def test_invalid_backend_rejected():
    """ONNX was deliberately removed (Finding 1) — Pydantic Literal must enforce."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, debug=True, inference_backend="onnx")


def test_arbitrary_string_rejected():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, debug=True, inference_backend="float64_super")
