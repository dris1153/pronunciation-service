import numpy as np

from app.services.v2.gop_features import analyse_posteriors, greedy_decode

VOCAB = ["<blank>", "a", "b", "c", "d"]
ID = {p: i for i, p in enumerate(VOCAB)}


def _posteriors(seq: list[str], frames_per: int = 3, gap: int = 2) -> np.ndarray:
    """Confident frames for each phone in ``seq`` separated by blank frames."""
    rows = []
    for ph in seq:
        for _ in range(frames_per):
            rows.append(ID[ph])
        rows += [0] * gap
    probs = np.full((len(rows), len(VOCAB)), 0.01)
    probs[np.arange(len(rows)), rows] = 0.96
    return np.log(probs / probs.sum(1, keepdims=True))


def test_greedy_decode_collapses_and_drops_blank():
    lp = _posteriors(["a", "a", "b"], frames_per=2, gap=1)
    assert greedy_decode(lp) == [ID["a"], ID["a"], ID["b"]]


def test_correct_speech_has_high_lpp_and_matching_heard():
    res = analyse_posteriors(_posteriors(["a", "b", "c"]), [("ab", ["a", "b"]), ("c", ["c"])], VOCAB)
    phones = [p for w in res.words for p in w.phones]
    assert [p.heard for p in phones] == ["a", "b", "c"]
    assert all(p.lpp > -0.1 for p in phones)
    assert all(len(p.features) == 1 + (len(VOCAB) - 1) + 1 for p in phones)
    assert res.words[1].start > res.words[0].end


def test_substitution_scores_low_and_is_heard():
    res = analyse_posteriors(_posteriors(["a", "d", "c"]), [("abc", ["a", "b", "c"])], VOCAB)
    a, b, c = res.words[0].phones
    assert b.heard == "d"
    assert b.lpp < a.lpp - 3 and b.lpp < c.lpp - 3


def test_deleted_phone_has_empty_heard():
    res = analyse_posteriors(_posteriors(["a", "c"], frames_per=4), [("abc", ["a", "b", "c"])], VOCAB)
    assert [p.heard for p in res.words[0].phones] == ["a", "", "c"]


def test_inserted_phone_attaches_to_preceding_word():
    res = analyse_posteriors(_posteriors(["a", "d", "b"]), [("a", ["a"]), ("b", ["b"])], VOCAB)
    assert res.words[0].inserted == ["d"]
    assert res.words[1].inserted == []


def test_phones_outside_vocab_are_dropped():
    res = analyse_posteriors(_posteriors(["a"]), [("a?", ["a", "?"])], VOCAB)
    assert [p.expected for p in res.words[0].phones] == ["a"]
