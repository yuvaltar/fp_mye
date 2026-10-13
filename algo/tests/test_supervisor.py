import numpy as np
import pandas as pd
import pytest

from tsm.supervisor import Supervisor, qlike, softmax_weights


def test_qlike_is_zero_when_perfect_and_positive_otherwise():
    assert qlike(0.2, 0.2) == pytest.approx(0)
    assert qlike(0.2, 0.3) > 0
    # Under-predicting costs more than over-predicting by the same factor.
    assert qlike(0.2, 0.1) > qlike(0.2, 0.4)


def test_softmax_weights():
    weights = softmax_weights(np.array([0.1, 0.2, 0.9]), temperature=0.1)
    assert weights.sum() == pytest.approx(1)
    assert weights[0] > weights[1] > weights[2]
    flat = softmax_weights(np.array([0.1, 0.2, 0.9]), temperature=1000)
    assert flat == pytest.approx([1 / 3] * 3, abs=1e-3)


def case(n=40):
    realized = pd.Series(np.full(n, 0.2))
    preds = pd.DataFrame({"good": np.full(n, 0.21), "bad": np.full(n, 0.6)})
    return preds, realized, np.arange(100, 100 + n)


def test_weights_sum_to_one_and_favor_the_better_skill():
    preds, realized, positions = case()
    out = Supervisor(window=10, temperature=0.1).combine(preds, realized, positions)
    assert out[["w_good", "w_bad"]].sum(axis=1).to_numpy() == pytest.approx(1)
    assert out["w_good"].iloc[-1] > 0.9
    assert out["supervisor"].iloc[-1] == pytest.approx(
        out["w_good"].iloc[-1] * 0.21 + out["w_bad"].iloc[-1] * 0.6
    )
    assert ((out["confidence"] >= 0) & (out["confidence"] <= 1)).all()


def test_equal_weights_until_an_outcome_is_known():
    preds, realized, positions = case()
    out = Supervisor(window=10).combine(preds, realized, positions)
    # The outcome of the first prediction is only known 5 days later.
    assert (out["w_good"].iloc[:5] == 0.5).all()
    assert out["w_good"].iloc[5] > 0.5


def test_supervisor_ignores_outcomes_not_known_yet():
    """Changing what happens after a date must not change that date's weights."""
    preds, realized, positions = case()
    changed = realized.copy()
    changed.iloc[20:] = 0.6  # outcomes of predictions 20+ are known from prediction 25 on
    a = Supervisor(window=10).combine(preds, realized, positions)
    b = Supervisor(window=10).combine(preds, changed, positions)
    columns = ["w_good", "w_bad", "supervisor", "confidence"]
    pd.testing.assert_frame_equal(a[columns].iloc[:25], b[columns].iloc[:25])
    assert not np.allclose(a["w_good"].iloc[25:], b["w_good"].iloc[25:])
