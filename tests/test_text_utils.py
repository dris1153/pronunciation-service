"""Tests for text utility functions."""
from __future__ import annotations

from app.utils.text import FILLER_WORDS, filter_fillers, normalise_text, text_to_words

# ── normalise_text ───────────────────────────────────────────────────────────


class TestNormaliseText:
    """Cover lowercase, punctuation stripping, whitespace, unicode, edge cases."""

    def test_lowercase(self):
        assert normalise_text("Hello World") == "hello world"

    def test_all_caps(self):
        assert normalise_text("HELLO WORLD") == "hello world"

    def test_mixed_case(self):
        assert normalise_text("hElLo WoRlD") == "hello world"

    def test_strip_punctuation(self):
        assert normalise_text("Hello, World!") == "hello world"

    def test_strip_special_chars(self):
        assert normalise_text("Hello@World#123") == "helloworld123"

    def test_collapse_whitespace(self):
        assert normalise_text("  hello   world  ") == "hello world"

    def test_tabs_and_newlines(self):
        assert normalise_text("hello\t\nworld") == "hello world"

    def test_keeps_apostrophes(self):
        assert normalise_text("don't") == "don't"

    def test_keeps_contractions(self):
        assert normalise_text("I'm can't won't") == "i'm can't won't"

    def test_empty_string(self):
        assert normalise_text("") == ""

    def test_only_whitespace(self):
        assert normalise_text("   ") == ""

    def test_only_punctuation(self):
        assert normalise_text("!!!...???") == ""

    def test_numbers_preserved(self):
        assert normalise_text("test 123") == "test 123"

    def test_unicode_accents_stripped(self):
        result = normalise_text("cafe\u0301")
        assert result == "cafe"

    def test_leading_trailing_spaces(self):
        assert normalise_text("  hello  ") == "hello"

    def test_single_char(self):
        assert normalise_text("a") == "a"

    def test_hyphenated_words(self):
        result = normalise_text("well-known")
        assert result == "wellknown"

    def test_parentheses_removed(self):
        assert normalise_text("hello (world)") == "hello world"


# ── text_to_words ────────────────────────────────────────────────────────────


class TestTextToWords:
    """Cover splitting, normalisation integration, edge cases."""

    def test_simple(self):
        assert text_to_words("hello world") == ["hello", "world"]

    def test_with_punctuation(self):
        assert text_to_words("Hello, World!") == ["hello", "world"]

    def test_single_word(self):
        assert text_to_words("hello") == ["hello"]

    def test_multiple_spaces(self):
        assert text_to_words("hello    world") == ["hello", "world"]

    def test_empty_string(self):
        assert text_to_words("") == []

    def test_only_punctuation(self):
        assert text_to_words("!!!") == []

    def test_preserves_apostrophes(self):
        assert text_to_words("don't stop") == ["don't", "stop"]

    def test_upper_case(self):
        assert text_to_words("HELLO WORLD") == ["hello", "world"]

    def test_numbers_in_words(self):
        result = text_to_words("test 123 abc")
        assert result == ["test", "123", "abc"]

    def test_many_words(self):
        words = text_to_words("the quick brown fox jumps over the lazy dog")
        assert len(words) == 9
        assert words[0] == "the"
        assert words[-1] == "dog"


# ── filter_fillers ───────────────────────────────────────────────────────────


class TestFilterFillers:
    """Test filler / disfluency word removal."""

    def test_removes_uh(self):
        assert filter_fillers(["hello", "uh", "world"]) == ["hello", "world"]

    def test_removes_um(self):
        assert filter_fillers(["um", "hello"]) == ["hello"]

    def test_removes_multiple_fillers(self):
        assert filter_fillers(["uh", "hello", "um", "world", "hmm"]) == ["hello", "world"]

    def test_preserves_non_fillers(self):
        words = ["hello", "world", "foo"]
        assert filter_fillers(words) == ["hello", "world", "foo"]

    def test_empty_list(self):
        assert filter_fillers([]) == []

    def test_all_fillers(self):
        assert filter_fillers(["uh", "um", "hmm"]) == []

    def test_known_fillers_in_set(self):
        """All expected fillers should be in FILLER_WORDS."""
        for f in ["uh", "um", "uhm", "hmm", "hm", "mm", "ah", "eh", "er", "mhm", "umm"]:
            assert f in FILLER_WORDS

    def test_normal_words_not_fillers(self):
        """Common words must NOT be in FILLER_WORDS."""
        for w in ["hello", "the", "a", "is", "it", "like", "you", "I"]:
            assert w not in FILLER_WORDS
