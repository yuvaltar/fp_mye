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


# --- pooled mode (Step 15): every skill judged on all tickers together ---

from tsm.supervisor import pooled_weights  # noqa: E402


def pooled_case(n=30, tickers=("A", "B", "C")):
    """Three tickers on common dates; skill "good" is close on A and B, "bad" is far everywhere."""
    rows = []
    for t in tickers:
        for i in range(n):
            rows.append({"ticker": t, "position": 100 + i, "good": 0.21 if t != "C" else 0.5, "bad": 0.6, "realized": 0.2})
    return pd.DataFrame(rows)


def test_pooled_weights_match_a_hand_computation():
    frame = pooled_case()
    out = pooled_weights(frame[["good", "bad"]], frame["realized"], frame["position"], window=3, temperature=0.1)
    # Position 110: known outcomes are positions <= 105; the window keeps 103, 104, 105, on all 3 tickers.
    good = np.mean([qlike(0.2, 0.21)] * 6 + [qlike(0.2, 0.5)] * 3)
    bad = qlike(0.2, 0.6)
    expected = softmax_weights(np.array([good, bad]), 0.1)
    assert out.loc[110].to_numpy() == pytest.approx(expected)
    # Nothing known before position 105: equal weights.
    assert out.loc[100:104].to_numpy() == pytest.approx(0.5)


def test_pooled_weights_ignore_outcomes_not_known_yet():
    frame = pooled_case()
    changed = frame["realized"].copy()
    changed[frame["position"] >= 115] = 0.9  # outcomes of positions 115+ are known from 120 on
    a = pooled_weights(frame[["good", "bad"]], frame["realized"], frame["position"], window=5, temperature=0.1)
    b = pooled_weights(frame[["good", "bad"]], changed, frame["position"], window=5, temperature=0.1)
    pd.testing.assert_frame_equal(a.loc[:119], b.loc[:119])
    assert not np.allclose(a.loc[120:].to_numpy(), b.loc[120:].to_numpy())


def test_pooled_weights_skip_unknown_outcomes():
    frame = pooled_case()
    realized = frame["realized"].copy()
    realized[(frame["ticker"] == "C") & (frame["position"] == 103)] = np.nan
    out = pooled_weights(frame[["good", "bad"]], realized, frame["position"], window=1, temperature=0.1)
    # Position 108 judges position 103 only, where ticker C's outcome is unknown: A and B alone.
    expected = softmax_weights(np.array([qlike(0.2, 0.21), qlike(0.2, 0.6)]), 0.1)
    assert out.loc[108].to_numpy() == pytest.approx(expected)


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        Supervisor(mode="by_sector")
