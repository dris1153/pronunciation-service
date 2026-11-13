"""Tests for training/phone_labels.py (label pipeline of the phone CTC model)."""
from __future__ import annotations

from training.phone_labels import BLANK, PHONE_TO_ID, VOCAB, ids_to_phones, words_to_ids


def test_vocab_is_blank_plus_41_ipa_symbols():
    assert VOCAB[0] == BLANK
    assert len(VOCAB) == 42
    assert len(set(VOCAB)) == 42


def test_known_word_maps_to_expected_phones():
    ids, dropped = words_to_ids("the cat")
    assert dropped == 0
    phones = ids_to_phones(ids)
    assert phones[-3:] == ["k", "æ", "t"]
    assert phones[0] == "ð"


def test_stressed_and_unstressed_ah_are_distinct_phones():
    # "about" starts with unstressed AH0 (ə); "cup" has stressed AH1 (ʌ)
    assert ids_to_phones(words_to_ids("about")[0])[0] == "ə"
    assert "ʌ" in ids_to_phones(words_to_ids("cup")[0])


def test_blank_never_emitted_as_label():
    ids, _ = words_to_ids("hello world")
    assert PHONE_TO_ID[BLANK] not in ids


def test_oov_word_still_gets_labels():
    ids, _ = words_to_ids("zorbflax")
    assert len(ids) > 0


def test_empty_text():
    assert words_to_ids("") == ([], 0)
