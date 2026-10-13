"""The earnings layer: reaction days, earnings weeks, the jump, split calibration, and no look-ahead."""
import numpy as np
import pandas as pd
import pytest

from tsm import backtest, earnings_layer as layer
from tsm.data import truncate_panel
from tsm.skills.base import MIN_VOL, TemporalSkill
from tsm.skills.short_term import ShortTermSkill
from tsm.target import realized_vol

from tests.conftest import corrupt_after, release_table
from tests.conftest import with_reaction_jumps as with_jumps

START = "2018-01-01"  # row 260 of the synthetic panel
TUNE_BEFORE = "2018-05-01"
CUT = 380
NAMES = ["short_term", "trailing"]


class TrailingSkill(TemporalSkill):
    """A cheap causal skill: the volatility of the last 22 days."""

    name = "trailing"
    horizon = "medium"
    refit_every_days = 1000

    def fit(self, panel):
        pass

    def predict(self, panel):
        return {t: max(float(realized_vol(f["close"], 22).iloc[-1]), MIN_VOL) for t, f in panel.items()}


def releases(panel, rows=(100, 140, 180, 220, 260, 300, 340, 370, 395, 410)):
    days = next(iter(panel.values())).index
    out = []
    for ticker in ("AAA", "BBB"):
        for i, row in enumerate(rows):
            shift = 3 if ticker == "BBB" else 0
            out.append({"ticker": ticker, "date": days[row + shift], "timing": ("before_open", "after_close")[i % 2]})
    return pd.DataFrame(out)


def run(panel, release_rows, variant):
    raw = backtest.run_skills(panel, [ShortTermSkill(), TrailingSkill()], start=START)
    calendar = layer.trading_calendar(next(iter(panel.values())).index)
    reactions = layer.reaction_positions(release_rows, calendar)
    return layer.run_variant(raw, panel, NAMES, reactions, variant, tune_before=TUNE_BEFORE)


def forecast_columns(frame):
    columns = [c for c in frame.columns if c.startswith(("pred_", "raw_pred_", "c_", "w_"))]
    return columns + ["supervisor", "confidence", "naive", "equal_weight", "baseline", "earnings_week"]


def test_reaction_day_before_the_open_after_the_close_and_on_a_weekend():
    calendar = pd.bdate_range("2024-01-01", "2024-01-31")
    rows = pd.DataFrame(
        {
            "ticker": ["A", "B", "C", "D"],
            "date": pd.to_datetime(["2024-01-10", "2024-01-10", "2024-01-10", "2024-01-06"]),
            "timing": ["before_open", "after_close", "unknown", "after_close"],
        }
    )
    got = {t: calendar[p[0]] for t, p in layer.reaction_positions(rows, calendar).items()}
    assert got == {
        "A": pd.Timestamp("2024-01-10"),
        "B": pd.Timestamp("2024-01-11"),
        "C": pd.Timestamp("2024-01-10"),
        "D": pd.Timestamp("2024-01-08"),  # a Saturday release reacts on Monday
    }


def test_an_earnings_week_has_a_reaction_in_the_next_five_days():
    frame = pd.DataFrame({"ticker": "A", "position": np.arange(30)})
    flags = layer.earnings_weeks(frame, {"A": np.array([20])})
    assert np.flatnonzero(flags).tolist() == [15, 16, 17, 18, 19]  # p+1..p+5 contains 20; p = 20 does not


def test_reaction_excess_is_the_squared_move_beyond_ordinary_days():
    returns = np.full(400, 0.01)
    returns[300] = 0.05
    close = pd.Series(100 * np.exp(np.cumsum(returns)))
    out = layer.reaction_excess(close, np.array([100, 300]))
    assert out["day"].tolist() == [300]  # 100 has no full window of 250 days behind it
    assert out["excess"].iloc[0] == pytest.approx(0.05**2 - 0.01**2)


def test_the_jump_is_shrunk_toward_all_tickers_and_uses_past_reactions_only():
    days = pd.bdate_range("2017-01-02", periods=500)
    moves = {"A": 0.05, "B": 0.03}  # reaction-day moves, ordinary days 0.01
    panel, reactions = {}, {}
    for ticker, move in moves.items():
        returns = np.full(len(days), 0.01)
        reactions[ticker] = np.array([300, 360, 420])
        returns[reactions[ticker]] = move
        panel[ticker] = pd.DataFrame({"close": 100 * np.exp(np.cumsum(returns))}, index=days)
    frame = pd.DataFrame({"ticker": ["A", "A", "A"], "position": [299, 300, 370]})
    jumps = layer.jump_sizes(frame, panel, reactions)
    excess = {t: m**2 - 0.01**2 for t, m in moves.items()}
    overall = np.mean(list(excess.values()))
    assert jumps[0] == 0.0  # before any reaction
    assert jumps[1] == pytest.approx(0.2 * excess["A"] + 0.8 * overall)  # n = 1: weight 1/5
    assert jumps[2] == pytest.approx(2 / 6 * excess["A"] + 4 / 6 * overall)  # n = 2: weight 2/6


def test_the_jump_adds_one_reaction_to_the_five_day_variance():
    frame = pd.DataFrame({"pred_x": [0.2, 0.2], "earnings_week": [True, False]})
    out = layer.add_jump(frame, ["x"], np.array([0.0004, 0.0004]))
    assert out["pred_x"].tolist() == pytest.approx([np.sqrt(0.04 + 252 / 5 * 0.0004), 0.2])


def test_split_calibration_has_one_factor_per_kind_of_week():
    n = 400
    week = (np.arange(n) % 10) < 2
    frame = pd.DataFrame(
        {
            "date": pd.bdate_range("2020-01-01", periods=n),
            "ticker": "A",
            "position": np.arange(n),
            "pred_x": 0.2,
            "earnings_week": week,
        }
    )
    frame["realized_vol"] = np.where(week, 0.4, 0.2)  # earnings weeks run twice as hot
    out = layer.split_calibrate(frame, ["x"])
    late = frame["position"] > 300
    assert out.loc[late & week, "c_x"].to_numpy() == pytest.approx(2.0)
    assert out.loc[late & ~week, "c_x"].to_numpy() == pytest.approx(1.0)
    assert out["raw_pred_x"].eq(0.2).all()


def test_the_unchanged_committee_is_the_backtest(panel):
    """variant "none" must be exactly the backtest's own downstream steps."""
    frame, supervisor = run(panel, releases(panel), "none")
    raw = backtest.run_skills(panel, [ShortTermSkill(), TrailingSkill()], start=START)
    expected = backtest.add_targets_and_baselines(raw, panel, NAMES)
    tuned = backtest.tune_supervisor(expected, NAMES, before=TUNE_BEFORE)
    expected = backtest.apply_supervisor(expected, tuned, NAMES)
    assert supervisor == tuned
    columns = [c for c in forecast_columns(frame) if c != "earnings_week"]
    pd.testing.assert_frame_equal(frame[columns], expected[columns])


@pytest.mark.parametrize("variant", ["jump", "split"])
def test_no_future_leakage(panel, variant):
    """Prices after p, and releases reacting after p+5, must not move any forecast up to p.

    The panel has real reaction moves, so J is not floored to 0. AAA reacts at
    CUT+2: its date is known ahead (it flags the forecasts before it), but its price
    move after CUT must not be used before it happens. BBB's next release reacts at
    CUT+8, beyond the known horizon, and is dropped from the second run; so are
    later releases of both.
    """
    history = [(t, r + (3 if t == "BBB" else 0), ("before_open", "after_close")[i % 2])
               for t in ("AAA", "BBB") for i, r in enumerate((100, 140, 180, 220, 260, 300, 340, 370))]
    near = [("AAA", CUT + 2, "before_open")]
    known = release_table(panel, history + near + [("BBB", CUT + 7, "after_close"), ("AAA", 395, "after_close"), ("BBB", 410, "before_open")])
    later = release_table(panel, history + near + [("AAA", 400, "before_open")])
    panel = with_jumps(panel, known)
    clean, sup_clean = run(panel, known, variant)
    dirty, sup_dirty = run(corrupt_after(panel, CUT), later, variant)
    assert sup_clean == sup_dirty
    upto = clean["position"] <= CUT
    columns = forecast_columns(clean)
    assert {f"c_{n}" for n in NAMES} | {f"raw_pred_{n}" for n in NAMES} <= set(columns)
    pd.testing.assert_frame_equal(clean.loc[upto, columns], dirty.loc[upto, columns])
    after = clean["position"] > CUT + 5
    assert not np.allclose(clean.loc[after, "supervisor"], dirty.loc[after, "supervisor"])


def test_a_release_within_five_days_is_known_ahead_by_assumption(panel):
    """The flip side: a release reacting at p+1..p+5 does change the forecast at p, by design."""
    panel = with_jumps(panel, releases(panel))
    clean, _ = run(panel, releases(panel), "jump")
    without = releases(panel)
    without = without[~((without["ticker"] == "AAA") & (without["date"] == next(iter(panel.values())).index[370]))]
    changed, _ = run(panel, without, "jump")
    p = clean[(clean["ticker"] == "AAA") & (clean["position"] == 368)].index
    assert clean.loc[p, "earnings_week"].item() and not changed.loc[p, "earnings_week"].item()
    # The forecast moves; raw_pred_ stays the model's own prediction (Step 13), with or without the release.
    assert clean.loc[p, "pred_trailing"].item() != changed.loc[p, "pred_trailing"].item()
    assert clean.loc[p, "raw_pred_trailing"].item() == changed.loc[p, "raw_pred_trailing"].item()
