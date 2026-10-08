"""The blocking rule: no information from the future, anywhere in the pipeline."""
import numpy as np
import pandas as pd
import pytest

from tsm import backtest
from tsm.skills.base import TemporalSkill
from tsm.skills.multivariate import MultivariateSkill
from tsm.skills.regime import RegimeSkill
from tsm.skills.short_term import ShortTermSkill
from tsm.skills.weak_signals import WeakSignalsSkill
from tsm.target import forward_realized_vol

from tests.conftest import corrupt_after

START = "2018-01-01"  # row 260 of the synthetic panel
TUNE_BEFORE = "2018-05-01"
CUT = 380  # prices after this row get corrupted


def fast_skills():
    return [
        ShortTermSkill(),
        RegimeSkill(),
        WeakSignalsSkill(),
        MultivariateSkill(input_size=20, hidden_size=8, max_steps=5),
    ]


def run(panel, monkeypatch):
    monkeypatch.setattr(backtest, "BACKTEST_START", START)
    skills = fast_skills()
    names = [s.name for s in skills]
    frame = backtest.add_targets_and_baselines(backtest.run_skills(panel, skills, start=START), panel, names)
    supervisor = backtest.tune_supervisor(frame, names, before=TUNE_BEFORE)
    return backtest.apply_supervisor(frame, supervisor, names), supervisor


class RecordingSkill(TemporalSkill):
    name = "recorder"
    horizon = "short"
    refit_every_days = 7

    def __init__(self):
        self.seen = []

    def fit(self, panel):
        self.seen.append(("fit", {t: f.index[-1] for t, f in panel.items()}))

    def predict(self, panel):
        self.seen.append(("predict", {t: f.index[-1] for t, f in panel.items()}))
        return {t: 0.2 for t in panel}


def test_skills_never_receive_rows_after_the_as_of_date(panel):
    skill = RecordingSkill()
    frame = backtest.run_skills(panel, [skill], start=START)
    as_of_dates = sorted(frame["date"].unique())
    predict_calls = [last for kind, last in skill.seen if kind == "predict"]
    assert len(predict_calls) == len(as_of_dates)
    for as_of, last_rows in zip(as_of_dates, predict_calls):
        assert set(last_rows.values()) == {as_of}
    # Every fit happens on the date of the predict call that follows it.
    for (kind, last), (_, next_last) in zip(skill.seen, skill.seen[1:]):
        if kind == "fit":
            assert last == next_last


def test_no_future_leakage_in_the_whole_pipeline(panel, monkeypatch):
    """Corrupt every price after a date: nothing computed up to that date may change.

    Covers the skills (features, training rows), the baselines, the supervisor's
    tuning, its weights and its confidence.
    """
    clean, supervisor_clean = run(panel, monkeypatch)
    dirty, supervisor_dirty = run(corrupt_after(panel, CUT), monkeypatch)
    assert supervisor_clean == supervisor_dirty

    upto = clean["position"] <= CUT
    forecasts = [c for c in clean.columns if c.startswith(("pred_", "w_"))]
    forecasts += ["supervisor", "confidence", "naive", "equal_weight", "baseline"]
    pd.testing.assert_frame_equal(clean.loc[upto, forecasts], dirty.loc[upto, forecasts])

    # Sanity check that the corruption is real and visible after the cut.
    after = clean["position"] > CUT + 5
    assert not np.allclose(clean.loc[after, "supervisor"], dirty.loc[after, "supervisor"])


def test_realized_vol_is_the_future_and_unknown_at_the_end(panel, monkeypatch):
    frame, _ = run(panel, monkeypatch)
    one = frame[frame["ticker"] == "AAA"].set_index("position")
    expected = forward_realized_vol(panel["AAA"]["close"]).to_numpy()
    assert one["realized_vol"].iloc[10] == pytest.approx(expected[one.index[10]])
    assert one["realized_vol"].iloc[-5:].isna().all()
    assert one["realized_vol"].iloc[:-5].notna().all()
    # The last prediction is made on the last available day.
    assert one.index[-1] == len(panel["AAA"]) - 1


def test_weights_sum_to_one_everywhere(panel, monkeypatch):
    frame, _ = run(panel, monkeypatch)
    weights = frame[[c for c in frame.columns if c.startswith("w_")]]
    assert weights.sum(axis=1).to_numpy() == pytest.approx(1)
    assert frame["supervisor"].notna().all() and (frame["supervisor"] > 0).all()
