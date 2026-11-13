import numpy as np

from app.services.v2.gop_features import PhoneAnalysis, V2Analysis, WordAnalysis
from app.services.v2.scorer import PHONES, UTT_TARGETS, Linear, Mlp, Scorer, phone_features, utt_features


def _analysis() -> V2Analysis:
    def ph(expected: str, heard: str, start: int) -> PhoneAnalysis:
        return PhoneAnalysis(expected, heard, start, start + 2, lpp=-0.5, features=np.full(43, 0.1))

    return V2Analysis([
        WordAnalysis("go", [ph("ɡ", "ɡ", 0), ph("oʊ", "", 3)]),
        WordAnalysis("at", [ph("æ", "ɛ", 10), ph("t", "t", 13)], inserted=["s"]),
    ], [], 30)


def test_mlp_matches_manual_forward_and_clips_z():
    w1, b1 = np.array([[1.0, -1.0]]), np.array([0.0, 0.5])
    w2, b2 = np.array([[2.0], [3.0]]), np.array([0.25])
    m = Mlp(np.array([0.0]), np.array([1.0]), [(w1, b1), (w2, b2)])
    assert np.allclose(m.predict(np.array([[2.0]])), [2.0 * 2 + 0.0 * 3 + 0.25])  # relu(2,-1.5)=(2,0)
    assert np.allclose(m.predict(np.array([[1e6]])), m.predict(np.array([[10.0]])))  # z clipped at 10


def test_json_roundtrip():
    lin = Linear(np.zeros(2), np.ones(2), np.array([1.0, 2.0]), 0.5)
    assert np.allclose(Linear.from_json(lin.to_json()).predict(np.array([1.0, 1.0])), 3.5)
    m = Mlp(np.zeros(2), np.ones(2), [(np.ones((2, 1)), np.zeros(1))])
    assert np.allclose(Mlp.from_json(m.to_json()).predict(np.ones((1, 2))), 2.0)


def test_phone_feature_shape_and_mismatch_flags():
    mats = phone_features(_analysis())
    assert [m.shape[0] for m in mats] == [2, 2]
    assert len({m.shape[1] for m in mats}) == 1
    onehot_start = 43 + 2
    flags = slice(onehot_start + len(PHONES), onehot_start + len(PHONES) + 3)  # deleted, same-group sub, other sub
    assert mats[0][1, flags].tolist() == [1, 0, 0]  # deleted
    assert mats[1][0, flags].tolist() == [0, 1, 0]  # æ -> ɛ same group


def test_score_clips_to_ranges_and_has_all_heads():
    a = _analysis()
    n_phone = phone_features(a)[0].shape[1]
    n_utt = len(utt_features(a, [[1.0, 1.0], [1.0, 1.0]], [5.0, 5.0]))
    huge = lambda n, b: Linear(np.zeros(n), np.ones(n), np.zeros(n), b)  # noqa: E731
    sc = Scorer(Mlp(np.zeros(n_phone), np.ones(n_phone), [(np.zeros((n_phone, 1)), np.array([9.0]))]),
                huge(11, 99.0), {t: huge(n_utt, -5.0) for t in UTT_TARGETS}, 1.0)
    out = sc.score(a)
    assert out.phone == [[2.0, 2.0], [2.0, 2.0]]
    assert out.word == [10.0, 10.0]
    assert set(out.utt) == set(UTT_TARGETS) and all(v == 0.0 for v in out.utt.values())
    assert out.completeness == 7.5  # 1 of 4 phones deleted
