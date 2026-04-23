"""Tests asserting consistency across the three phoneme mapping tables.

All three mappings must cover exactly the same set of 41 IPA symbols:
  - _ARPABET_TO_IPA  (ipa_service.py)   : ARPAbet → IPA values
  - _IPA_TO_WAV2VEC  (gop_service.py)   : IPA keys
  - _PHONEME_GROUPS  (pronunciation_service.py) : union of all group sets
"""
from __future__ import annotations

from app.services.gop_service import _IPA_TO_WAV2VEC
from app.services.ipa_service import _ARPABET_TO_IPA
from app.services.pronunciation_service import _PHONEME_GROUPS

# Expected canonical count per architecture documentation
_EXPECTED_SYMBOL_COUNT = 41


def _arpabet_ipa_values() -> set[str]:
    """All IPA symbols produced by the ARPAbet→IPA mapping."""
    return set(_ARPABET_TO_IPA.values())


def _wav2vec_ipa_keys() -> set[str]:
    """All IPA symbols consumed by the IPA→Wav2Vec2 mapping."""
    return set(_IPA_TO_WAV2VEC.keys())


def _phoneme_groups_union() -> set[str]:
    """Union of all phoneme groups used for similarity scoring."""
    result: set[str] = set()
    for group in _PHONEME_GROUPS:
        result |= group
    return result


class TestPhonemeMappingSync:
    """All three phoneme tables must reference exactly the same IPA symbols."""

    def test_arpabet_values_match_wav2vec_keys(self):
        """_ARPABET_TO_IPA values must equal _IPA_TO_WAV2VEC keys."""
        arpabet_ipa = _arpabet_ipa_values()
        wav2vec_ipa = _wav2vec_ipa_keys()
        only_in_arpabet = arpabet_ipa - wav2vec_ipa
        only_in_wav2vec = wav2vec_ipa - arpabet_ipa
        assert not only_in_arpabet, (
            f"IPA symbols in _ARPABET_TO_IPA but missing from _IPA_TO_WAV2VEC: "
            f"{sorted(only_in_arpabet)}"
        )
        assert not only_in_wav2vec, (
            f"IPA symbols in _IPA_TO_WAV2VEC but missing from _ARPABET_TO_IPA: "
            f"{sorted(only_in_wav2vec)}"
        )

    def test_arpabet_values_match_phoneme_groups(self):
        """_ARPABET_TO_IPA values must equal the union of _PHONEME_GROUPS."""
        arpabet_ipa = _arpabet_ipa_values()
        groups_ipa = _phoneme_groups_union()
        only_in_arpabet = arpabet_ipa - groups_ipa
        only_in_groups = groups_ipa - arpabet_ipa
        assert not only_in_arpabet, (
            f"IPA symbols in _ARPABET_TO_IPA but missing from _PHONEME_GROUPS: "
            f"{sorted(only_in_arpabet)}"
        )
        assert not only_in_groups, (
            f"IPA symbols in _PHONEME_GROUPS but missing from _ARPABET_TO_IPA: "
            f"{sorted(only_in_groups)}"
        )

    def test_wav2vec_keys_match_phoneme_groups(self):
        """_IPA_TO_WAV2VEC keys must equal the union of _PHONEME_GROUPS."""
        wav2vec_ipa = _wav2vec_ipa_keys()
        groups_ipa = _phoneme_groups_union()
        only_in_wav2vec = wav2vec_ipa - groups_ipa
        only_in_groups = groups_ipa - wav2vec_ipa
        assert not only_in_wav2vec, (
            f"IPA symbols in _IPA_TO_WAV2VEC but missing from _PHONEME_GROUPS: "
            f"{sorted(only_in_wav2vec)}"
        )
        assert not only_in_groups, (
            f"IPA symbols in _PHONEME_GROUPS but missing from _IPA_TO_WAV2VEC: "
            f"{sorted(only_in_groups)}"
        )

    def test_all_three_mappings_cover_41_symbols(self):
        """All three mappings must collectively cover exactly 41 IPA symbols."""
        arpabet_ipa = _arpabet_ipa_values()
        wav2vec_ipa = _wav2vec_ipa_keys()
        groups_ipa = _phoneme_groups_union()
        # All sets must be equal (tested above); check count against architecture spec
        assert len(arpabet_ipa) == _EXPECTED_SYMBOL_COUNT, (
            f"_ARPABET_TO_IPA has {len(arpabet_ipa)} unique IPA values, "
            f"expected {_EXPECTED_SYMBOL_COUNT}"
        )
        assert len(wav2vec_ipa) == _EXPECTED_SYMBOL_COUNT, (
            f"_IPA_TO_WAV2VEC has {len(wav2vec_ipa)} keys, "
            f"expected {_EXPECTED_SYMBOL_COUNT}"
        )
        assert len(groups_ipa) == _EXPECTED_SYMBOL_COUNT, (
            f"_PHONEME_GROUPS union has {len(groups_ipa)} symbols, "
            f"expected {_EXPECTED_SYMBOL_COUNT}"
        )

    def test_phoneme_groups_no_duplicates(self):
        """No IPA symbol should appear in more than one phoneme group."""
        seen: set[str] = set()
        duplicates: list[str] = []
        for group in _PHONEME_GROUPS:
            for ph in group:
                if ph in seen:
                    duplicates.append(ph)
                seen.add(ph)
        assert not duplicates, (
            f"Phonemes appear in multiple groups: {sorted(duplicates)}"
        )

    def test_wav2vec_values_are_strings(self):
        """All _IPA_TO_WAV2VEC values must be non-empty strings (token names)."""
        for ipa_key, wav2vec_token in _IPA_TO_WAV2VEC.items():
            assert isinstance(wav2vec_token, str) and wav2vec_token, (
                f"Token for IPA '{ipa_key}' is empty or not a string"
            )
