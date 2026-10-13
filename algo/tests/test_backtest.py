"""The blocking rule: no information from the future, anywhere in the pipeline."""
import numpy as np
import pandas as pd
import pytest

from tsm import backtest
from tsm.models.itransformer import ITransformerSkill
from tsm.skills.itransformer import ITransformerCommitteeSkill
from tsm.skills.base import TemporalSkill
from tsm.skills.multivariate import MultivariateSkill
from tsm.skills.regime import RegimeSkill
from tsm.skills.short_term import ShortTermSkill
from tsm.skills.weak_signals import WeakSignalsSkill
from tsm.target import forward_realized_vol

from tests.conftest import corrupt_after, release_table, with_reaction_jumps

START = "2018-01-01"  # row 260 of the synthetic panel
TUNE_BEFORE = "2018-05-01"
CUT = 380  # prices after this row get corrupted


# The graph candidates' "sector" source needs a sector for the synthetic tickers.
pytestmark = pytest.mark.usefixtures("synthetic_sectors")


def fast_skills():
    """The committee plus the experiment candidates, all shrunk to run fast.

    The candidates are not in build_skills, but the leakage rule applies to them
    just the same, so the whole-pipeline corruption test below covers them too.
    """
    return [
        ShortTermSkill(),
        RegimeSkill(),
        WeakSignalsSkill(),
        ITransformerCommitteeSkill(input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5),
        MultivariateSkill(input_size=20, hidden_size=8, max_steps=5),
        ITransformerSkill(loss="mae", input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5),
        ITransformerSkill(loss="qlike", input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5),
        ITransformerSkill(
            loss="mae", path=True, input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5
        ),
        ITransformerSkill(
            loss="mae", path=True, features=True,
            input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5,
        ),
        ITransformerSkill(
            loss="mae", path=True, features=True, gap_vix=True,
            input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5,
        ),
        *[
            ITransformerSkill(
                loss="mae", path=True, features=True, graph=mode, graph_source=source,
                input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5,
            )
            for mode in ("gnn", "bias")
            for source in ("corr", "sector", "shuffled")
        ],
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
    forecasts = [c for c in clean.columns if c.startswith(("pred_", "raw_pred_", "c_", "w_"))]
    forecasts += ["supervisor", "confidence", "naive", "equal_weight", "baseline"]
    # The calibration factors are built from realized outcomes, so they are the most
    # likely place for a leak: make sure they are in the compared columns.
    assert {f"c_{s.name}" for s in fast_skills()} <= set(forecasts)
    assert {f"raw_pred_{s.name}" for s in fast_skills()} <= set(forecasts)
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


def test_calibration_scales_the_raw_prediction_by_its_factor(panel, monkeypatch):
    frame, _ = run(panel, monkeypatch)
    for name in (s.name for s in fast_skills()):
        assert frame[f"pred_{name}"].to_numpy() == pytest.approx(
            (frame[f"raw_pred_{name}"] * frame[f"c_{name}"]).to_numpy(), nan_ok=True
        )
        # The raw prediction is kept untouched, and the factor is always usable.
        assert frame[f"c_{name}"].notna().all() and (frame[f"c_{name}"] > 0).all()


def test_calibration_factor_matches_its_definition_on_known_outcomes_only(panel, monkeypatch):
    """Recompute c by hand for one date: pooled over tickers, last 250 known days, c = 1 with none."""
    frame, _ = run(panel, monkeypatch)
    positions = np.sort(frame["position"].unique())
    name = "short_term"
    for position in (positions[0], positions[3], positions[len(positions) // 2], positions[-1]):
        eligible = frame[frame["position"] <= position - 5]
        keep = np.sort(eligible["position"].unique())[-backtest.CALIBRATION_WINDOW:]
        window = eligible[eligible["position"].isin(keep)]
        ratio = (window["realized_vol"] / window[f"raw_pred_{name}"]).replace([np.inf, -np.inf], np.nan).dropna()
        expected = np.sqrt((ratio**2).mean()) if len(ratio) else 1.0
        actual = frame.loc[frame["position"] == position, f"c_{name}"].to_numpy()
        # Pooled over tickers: every ticker on this date shares one factor.
        assert actual == pytest.approx(actual[0])
        assert actual[0] == pytest.approx(expected)


def test_calibration_is_one_before_any_outcome_is_known(panel, monkeypatch):
    frame, _ = run(panel, monkeypatch)
    first = np.sort(frame["position"].unique())[:5]
    early = frame[frame["position"].isin(first)]
    for name in (s.name for s in fast_skills()):
        assert (early[f"c_{name}"] == 1.0).all()


def test_calibration_window_forgets_old_outcomes(panel, monkeypatch):
    """A short window must give different factors than a long one, and both stay leak-free."""
    frame, _ = run(panel, monkeypatch)
    names = [s.name for s in fast_skills()]
    raw = frame.drop(columns=[f"pred_{n}" for n in names]).rename(
        columns={f"raw_pred_{n}": f"pred_{n}" for n in names}
    )
    short = backtest.calibration_factors(raw, names, window=20)
    long = backtest.calibration_factors(raw, names, window=250)
    assert not np.allclose(short["short_term"].to_numpy(), long["short_term"].to_numpy())


# ---------------------------------------------------------------- with the earnings layer (Step 13)

def earnings_releases(panel, beyond_horizon=True):
    """Synthetic releases for AAA and BBB. AAA reacts at CUT+2 (known ahead by assumption, but its
    move is after the cut); BBB's next release reacts at CUT+8, beyond the 5-day horizon, and is
    left out of the second run together with the later ones."""
    rows = [(t, r + (3 if t == "BBB" else 0), ("before_open", "after_close")[i % 2])
            for t in ("AAA", "BBB") for i, r in enumerate((100, 140, 180, 220, 260, 300, 340, 370))]
    rows.append(("AAA", CUT + 2, "before_open"))
    if beyond_horizon:
        rows += [("BBB", CUT + 7, "after_close"), ("AAA", 395, "after_close"), ("BBB", 410, "before_open")]
    else:
        rows.append(("AAA", 400, "before_open"))
    return release_table(panel, rows)


def run_with_earnings(panel, releases, monkeypatch, skills=None):
    from tsm.earnings_jump import reaction_positions, trading_calendar

    monkeypatch.setattr(backtest, "BACKTEST_START", START)
    skills = fast_skills() if skills is None else skills
    raw = backtest.run_skills(panel, skills, start=START)
    reactions = reaction_positions(releases, trading_calendar(next(iter(panel.values())).index))
    return backtest.finish_pipeline(raw, panel, [s.name for s in skills], reactions, tune_before=TUNE_BEFORE)


def test_no_future_leakage_in_the_whole_pipeline_with_earnings(panel, monkeypatch):
    """The same rule with the earnings layer on: prices after the cut, and releases reacting more
    than 5 trading days after it, must not move anything computed up to the cut."""
    known = earnings_releases(panel)
    panel = with_reaction_jumps(panel, known)
    clean, supervisor_clean = run_with_earnings(panel, known, monkeypatch)
    dirty, supervisor_dirty = run_with_earnings(corrupt_after(panel, CUT), earnings_releases(panel, False), monkeypatch)
    assert supervisor_clean == supervisor_dirty

    upto = clean["position"] <= CUT
    forecasts = [c for c in clean.columns if c.startswith(("pred_", "raw_pred_", "c_", "w_"))]
    forecasts += ["supervisor", "confidence", "naive", "equal_weight", "baseline"]
    forecasts += ["earnings_week", "reaction_date", "earnings_J"]
    assert {f"c_{s.name}" for s in fast_skills()} <= set(forecasts)
    assert clean.loc[upto, "earnings_week"].any() and (clean.loc[upto, "earnings_J"] > 0).any()
    pd.testing.assert_frame_equal(clean.loc[upto, forecasts], dirty.loc[upto, forecasts])

    after = clean["position"] > CUT + 5
    assert not np.allclose(clean.loc[after, "supervisor"], dirty.loc[after, "supervisor"])


def test_with_earnings_the_raw_predictions_and_the_baseline_stay_plain(panel, monkeypatch):
    """raw_pred_<skill> is each model's own prediction and the HAR-RV baseline has no jump;
    the skills' forecasts get the jump in earnings weeks only."""
    releases = earnings_releases(panel)
    panel = with_reaction_jumps(panel, releases)
    skills = [ShortTermSkill(), RegimeSkill(), WeakSignalsSkill()]  # the property holds for any skills
    with_layer, _ = run_with_earnings(panel, releases, monkeypatch, skills)
    raw = backtest.run_skills(panel, skills, start=START)
    without, _ = backtest.finish_pipeline(raw, panel, [s.name for s in skills], tune_before=TUNE_BEFORE)

    for skill in skills:
        np.testing.assert_array_equal(with_layer[f"raw_pred_{skill.name}"], without[f"raw_pred_{skill.name}"])
    pd.testing.assert_series_equal(with_layer["baseline"], without["baseline"])
    week = with_layer["earnings_week"]
    jumped = np.sqrt(with_layer["raw_pred_short_term"] ** 2 + 252 / 5 * with_layer["earnings_J"])
    expected = np.where(week, jumped, with_layer["raw_pred_short_term"]) * with_layer["c_short_term"]
    np.testing.assert_allclose(with_layer["pred_short_term"], expected)
    assert with_layer.loc[week, "reaction_date"].notna().all() and with_layer.loc[~week, "reaction_date"].isna().all()
    days = next(iter(panel.values())).index
    gap = days.get_indexer(with_layer.loc[week, "reaction_date"]) - with_layer.loc[week, "position"].to_numpy()
    assert ((gap >= 1) & (gap <= 5)).all()  # the reaction it refers to is in p+1..p+5


def test_tickers_without_a_next_release_are_named():
    """Judged on release dates: a release far beyond the calendar's few extra days still counts."""
    from tsm.earnings_jump import without_next_release

    releases = pd.DataFrame(
        {"ticker": ["AAA", "AAA", "BBB"], "date": pd.to_datetime(["2026-07-30", "2026-11-02", "2026-07-30"])}
    )
    assert without_next_release(releases, ["AAA", "BBB", "SPY"], pd.Timestamp("2026-10-07")) == ["BBB", "SPY"]
