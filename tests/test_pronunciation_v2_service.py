from unittest.mock import MagicMock

import numpy as np

from app.models.schemas import ErrorType, PronunciationResponse, PronunciationResponseV2
from app.services.v2.gop_features import PhoneAnalysis, V2Analysis, WordAnalysis
from app.services.v2.pronunciation_v2_service import PronunciationV2Service, remap_total
from app.services.v2.scorer import Scores


def _service(threshold: float = 1.0) -> PronunciationV2Service:
    ipa = MagicMock()
    ipa.word_to_ipa.side_effect = lambda w: f"/{w}/"
    ipa.text_to_ipa.side_effect = lambda t: " ".join(f"/{w}/" for w in t.lower().replace(",", "").split())
    scorer = MagicMock()
    scorer.mdd_threshold = threshold
    return PronunciationV2Service(analyser=MagicMock(), scorer=scorer, ipa=ipa)


def _phone(expected: str, heard: str, start: int) -> PhoneAnalysis:
    return PhoneAnalysis(expected, heard, start, start + 2, lpp=-0.5, features=np.zeros(43))


def _word(word: str, phones: list[tuple[str, str]], start: int, inserted: list[str] | None = None) -> WordAnalysis:
    return WordAnalysis(word, [_phone(e, h, start + 3 * i) for i, (e, h) in enumerate(phones)], inserted or [])


def _scores(phone: list[list[float]], word: list[float], total: float = 7.0) -> Scores:
    return Scores(phone, word, {"accuracy": 7.0, "fluency": 8.0, "prosodic": 6.0, "total": total}, 10.0)


def test_remap_total_is_monotone_and_stricter():
    assert remap_total(0) == 0 and remap_total(10) == 100
    assert remap_total(6.7) < 60 < 70 < remap_total(8.0)
    assert remap_total(5) < remap_total(6) < remap_total(7)


def test_is_correct_ipa_follows_scorer_flag_not_heard_phone():
    a = V2Analysis([_word("ab", [("a", "a"), ("b", "d")], 0)], [], 10)
    # a is heard correctly but scored low; b is a substitution but scored high
    resp = _service(threshold=1.0)._build_response("ab", a, _scores([[0.4, 1.9]], [7.0]))
    pa, pb = resp.results.word_details[0].phoneme_details
    assert (pa.is_correct_ipa, pb.is_correct_ipa) == (False, True)
    assert (pa.actual_ipa, pb.actual_ipa) == ("a", "d")
    assert pa.gop_score == 20.0 and pb.confidence_ipa == 0.3  # b/d: same group


def test_error_types_omission_and_mispronunciation_and_insertion_entry():
    words = [
        _word("gone", [("a", ""), ("b", "")], 0),           # every phone deleted -> Omission
        _word("bad", [("a", "a"), ("b", "b")], 10),         # low word score -> Mispronunciation
        _word("ok", [("a", "a")], 20, inserted=["s"]),      # fine, one inserted phone
    ]
    a = V2Analysis(words, [], 40)
    resp = _service()._build_response("gone bad ok", a, _scores([[0.1, 0.1], [0.5, 0.5], [1.9]], [1.0, 4.0, 9.0]))
    errors = [w.error_type for w in resp.results.word_details]
    assert errors == [ErrorType.OMISSION, ErrorType.MISPRONUNCIATION, ErrorType.NONE]
    ok_phones = resp.results.word_details[2].phoneme_details
    assert ok_phones[-1].expected_ipa == "" and ok_phones[-1].actual_ipa == "s" and not ok_phones[-1].is_correct_ipa
    assert not any(w.error_type == ErrorType.INSERTION for w in resp.results.word_details)


def test_unexpected_break_is_flagged_from_word_gap():
    # 20 ms frames: a 60-frame gap = 1.2 s > 0.8 s
    words = [_word("a", [("a", "a")], 0), _word("b", [("b", "b")], 62)]
    resp = _service()._build_response("a b", V2Analysis(words, [], 70), _scores([[1.9], [1.9]], [9.0, 9.0]))
    assert resp.results.word_details[1].error_type == ErrorType.UNEXPECTED_BREAK


def test_timing_and_headline_scores():
    words = [_word("a", [("a", "a")], 5), _word("b", [("b", "b")], 20)]
    resp = _service()._build_response("a b", V2Analysis(words, [], 40), _scores([[1.9], [1.9]], [9.0, 9.0], total=8.0))
    assert [(w.start_ms, w.end_ms) for w in resp.results.word_details] == [(100, 140), (400, 440)]
    assert resp.overall_score == remap_total(8.0)
    assert resp.accuracy_score == 70.0 and resp.fluency_score == 80.0 and resp.prosody_score == 60.0
    assert resp.transcribed_text == resp.results.actual_ipa == "a b"


def test_v2_json_is_superset_of_v1_keys():
    resp = _service()._zero_score_response("hello world")
    v1_top = set(PronunciationResponse.model_fields)
    assert v1_top <= set(resp.model_dump())
    word = resp.model_dump()["results"]["word_details"][0]
    assert {"start_ms", "end_ms"} <= set(word)
    assert isinstance(resp, PronunciationResponseV2) and resp.overall_score == 0.0
    assert all(w.error_type == ErrorType.OMISSION for w in resp.results.word_details)
