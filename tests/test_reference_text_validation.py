"""Tests for reference-text validator — Phase 01 / Finding 10."""
from __future__ import annotations

import pytest

from app.utils.text import validate_reference_text


def test_accepts_normal_text():
    assert validate_reference_text("hello world") == "hello world"


def test_accepts_max_length_text():
    text = "a " * 50  # 100 chars, 50 words
    assert validate_reference_text(text.strip()) == text.strip()


def test_rejects_too_many_chars():
    with pytest.raises(ValueError, match="500 characters"):
        validate_reference_text("a" * 501)


def test_rejects_too_many_words():
    text = " ".join(["a"] * 101)
    with pytest.raises(ValueError, match="100 words"):
        validate_reference_text(text)


def test_rejects_overlong_word():
    with pytest.raises(ValueError, match="30 characters"):
        validate_reference_text("supercalifragilisticexpialidocious_extended_extra")


def test_rejects_newline_control_char():
    with pytest.raises(ValueError, match="control characters"):
        validate_reference_text("hello\nworld")


def test_rejects_null_byte():
    with pytest.raises(ValueError, match="control characters"):
        validate_reference_text("hello\x00world")


def test_normalises_nfkc():
    # Full-width digits (U+FF11) → ASCII '1' under NFKC.
    result = validate_reference_text("number １")
    assert "1" in result
