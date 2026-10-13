"""The earnings jump: one expected earnings move added to a forecast whose window holds a release.

Shared by the product (``tsm.backtest``, on by default since Step 13) and the
experiment that chose it (``tsm.earnings_layer``, variant A).

Reaction day of a release: the release day if it comes before the open (or at an
unknown time, or during the session), the next trading day if after the close; a
release on a non-trading day reacts on the next trading day. A forecast made on
day p is an **earnings week** for a ticker when a reaction day falls in
p+1..p+5. **Assumption:** release dates, and their time of day, are known at
least 5 trading days ahead (companies announce them weeks ahead), which is
exactly what this flag needs.

In an earnings week the predicted variance gets one jump,
``vol_adj = sqrt(vol^2 + 252/5 * J)``. ``J`` is the ticker's expected excess
squared log return on a reaction day: the mean over its past reactions of (r^2
minus its mean squared return on ordinary days of the 250 trading days before),
floored at 0, shrunk toward the mean over all tickers with weight n/(n+4), n its
number of past reactions. Only reactions on or before p count, and only those
with 250 trading days of prices before them.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

from tsm.config import HORIZON_DAYS, TRADING_DAYS_PER_YEAR
from tsm.data import Panel
from tsm.earnings import load_earnings, to_trading_day

SHRINK = 4  # weight n / (n + SHRINK) on a ticker's own reactions
ORDINARY_WINDOW = 250  # trading days of ordinary returns behind each reaction
CALENDAR_EXTENSION = 10  # business days added after the last price day, for releases just after it


def trading_calendar(days: pd.DatetimeIndex, extra: int = CALENDAR_EXTENSION) -> pd.DatetimeIndex:
    """The price calendar plus a few business days after its end (holidays there are ignored).

    Only the last few forecasts, whose outcome is unknown and never scored, can
    look past the last price day.
    """
    return days.append(pd.bdate_range(days[-1] + pd.offsets.BDay(1), periods=extra))


def release_reactions(releases: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """One row per release inside the calendar: ``ticker``, ``report_date`` and its ``reaction`` position.

    ``releases`` has ``ticker``, ``date`` (midnight) and ``timing``. The one place
    the reaction-day rule is applied.
    """
    inside = releases[(releases["date"] >= calendar[0]) & (releases["date"] <= calendar[-1])]
    first = to_trading_day(inside["date"], calendar)
    on_trading_day = calendar[np.minimum(first, len(calendar) - 1)] == inside["date"].to_numpy()
    after_close = (inside["timing"].to_numpy() == "after_close") & on_trading_day
    out = pd.DataFrame(
        {"ticker": inside["ticker"].to_numpy(), "report_date": inside["date"].to_numpy(), "reaction": first + after_close}
    )
    return out[out["reaction"] < len(calendar)].reset_index(drop=True)


def reaction_positions(releases: pd.DataFrame, calendar: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Per ticker, the sorted calendar positions of its reaction days."""
    reactions = release_reactions(releases, calendar)
    return {ticker: np.unique(group["reaction"].to_numpy()) for ticker, group in reactions.groupby("ticker")}


def earnings_artifact(frame: pd.DataFrame, releases: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """``ticker``, ``report_date``, ``reaction_date`` for every reaction day an earnings week of ``frame`` refers to.

    The API's ``earnings_date`` is the day the company publishes its report; for an
    after-close report that is the trading day before the reaction day.
    ``predictions.csv`` only holds the reaction day and the earnings files are not
    committed, so the backtest writes this small table next to the predictions
    (``artifacts/earnings.csv``) and the API reads it from there.
    """
    table = release_reactions(releases, calendar)
    table["reaction_date"] = calendar[table["reaction"].to_numpy()]
    used = frame.loc[frame["earnings_week"].astype(bool), ["ticker", "reaction_date"]].drop_duplicates()
    used = used.assign(reaction_date=pd.to_datetime(used["reaction_date"]))
    out = table.merge(used, on=["ticker", "reaction_date"])[["ticker", "report_date", "reaction_date"]]
    if out.duplicated(["ticker", "reaction_date"]).any():
        raise ValueError("two releases of one ticker share a reaction day; the report date would be ambiguous")
    if len(out) != len(used):
        raise ValueError(f"{len(used) - len(out)} reaction days in the predictions have no release")
    return out.sort_values(["ticker", "reaction_date"]).reset_index(drop=True)


def load_releases() -> pd.DataFrame:
    """The saved Yahoo release dates, past and scheduled (``python -m tsm.earnings``)."""
    try:
        return load_earnings("yahoo")
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"{error}; run python -m tsm.earnings to save the earnings dates (or pass --no-earnings)"
        ) from None


def load_reactions(calendar: pd.DatetimeIndex) -> dict[str, np.ndarray]:
    """Reaction days from the saved Yahoo dates, past and scheduled."""
    return reaction_positions(load_releases(), calendar)


def next_reaction(frame: pd.DataFrame, reactions: dict[str, np.ndarray]) -> np.ndarray:
    """Calendar position of the first reaction day strictly after each row's day p, or -1."""
    out = np.full(len(frame), -1)
    positions = frame["position"].to_numpy()
    for ticker, rows in frame.groupby("ticker", sort=False).indices.items():
        days = reactions.get(ticker, np.empty(0, dtype=int))
        if days.size == 0:
            continue
        nxt = np.searchsorted(days, positions[rows], side="right")
        out[rows] = np.where(nxt < days.size, days[np.minimum(nxt, days.size - 1)], -1)
    return out


def earnings_weeks(frame: pd.DataFrame, reactions: dict[str, np.ndarray], horizon: int = HORIZON_DAYS) -> np.ndarray:
    """True where the forecast made on day p has a reaction day in p+1..p+horizon."""
    nxt = next_reaction(frame, reactions)
    return (nxt >= 0) & (nxt <= frame["position"].to_numpy() + horizon)


def without_next_release(releases: pd.DataFrame, tickers: list[str], last_day: pd.Timestamp) -> list[str]:
    """Tickers with no release dated after the last price day: their latest forecasts get no earnings week.

    Judged on the release dates themselves, not on reaction days: the calendar only
    reaches a few days past the last price day, and a release later than that is
    still a scheduled release (it just cannot fall in the latest forecasts' window).
    """
    scheduled = set(releases.loc[releases["date"] > last_day, "ticker"])
    return [t for t in tickers if t not in scheduled]


def reaction_excess(close: pd.Series, reactions: np.ndarray, window: int = ORDINARY_WINDOW) -> pd.DataFrame:
    """Per reaction day d: r_d^2 minus the mean r^2 of the ordinary days in d-window..d-1.

    Uses prices up to and including d only. Reactions without ``window`` trading
    days of returns before them are left out.
    """
    squared = np.square(np.log(close / close.shift(1)).to_numpy())
    days = reactions[reactions < len(squared)]
    ordinary = np.ones(len(squared), dtype=bool)
    ordinary[days] = False
    ordinary[0] = False  # no return on the first day
    sums = np.concatenate([[0.0], np.cumsum(np.where(ordinary, squared, 0.0))])
    counts = np.concatenate([[0], np.cumsum(ordinary)])
    days = days[days >= window + 1]  # a full window of returns behind it
    base = (sums[days] - sums[days - window]) / np.maximum(counts[days] - counts[days - window], 1)
    return pd.DataFrame({"day": days, "excess": squared[days] - base})


def jump_sizes(frame: pd.DataFrame, panel: Panel, reactions: dict[str, np.ndarray]) -> np.ndarray:
    """Shrunk J for every row of ``frame``, from reactions on or before its day p."""
    positions = np.sort(frame["position"].unique())
    tickers = list(panel)
    own = np.full((len(positions), len(tickers)), np.nan)  # floored mean excess per ticker, NaN if none yet
    count = np.zeros((len(positions), len(tickers)))
    for j, ticker in enumerate(tickers):
        excess = reaction_excess(panel[ticker]["close"], reactions.get(ticker, np.empty(0, dtype=int)))
        if excess.empty:
            continue
        known = np.searchsorted(excess["day"].to_numpy(), positions, side="right")  # reactions with day <= p
        running = np.concatenate([[np.nan], np.cumsum(excess["excess"].to_numpy())])
        with np.errstate(invalid="ignore", divide="ignore"):
            own[:, j] = np.maximum(running[known] / known, 0.0)
        count[:, j] = known
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # dates before any reaction: an empty mean, set to 0 below
        overall = np.nanmean(np.where(count > 0, own, np.nan), axis=1)  # mean over tickers with reactions
    overall = np.nan_to_num(overall, nan=0.0)
    weight = count / (count + SHRINK)
    shrunk = weight * np.nan_to_num(own, nan=0.0) + (1 - weight) * overall[:, None]
    rows = np.searchsorted(positions, frame["position"].to_numpy())
    cols = frame["ticker"].map({t: j for j, t in enumerate(tickers)}).to_numpy()
    return shrunk[rows, cols]


def add_jump(frame: pd.DataFrame, skill_names: list[str], jumps: np.ndarray) -> pd.DataFrame:
    """In earnings weeks, ``vol -> sqrt(vol^2 + 252/5 * J)`` for every skill's raw prediction."""
    frame = frame.copy()
    week = frame["earnings_week"].to_numpy()
    for name in skill_names:
        vol = frame[f"pred_{name}"].to_numpy()
        adjusted = np.sqrt(np.square(vol) + TRADING_DAYS_PER_YEAR / HORIZON_DAYS * jumps)
        frame[f"pred_{name}"] = np.where(week, adjusted, vol)
    return frame


def add_earnings_jump(
    frame: pd.DataFrame,
    panel: Panel,
    skill_names: list[str],
    reactions: dict[str, np.ndarray],
) -> pd.DataFrame:
    """The skills' raw predictions with the jump, plus what it was built from.

    Adds ``earnings_week``, ``reaction_date`` (the reaction day the earnings week
    refers to, empty otherwise) and ``earnings_J`` (the row's J, used only in an
    earnings week), keeps each model's own prediction in ``own_pred_<skill>``,
    and adds the jump to ``pred_<skill>``.
    """
    calendar = trading_calendar(next(iter(panel.values())).index)
    frame = frame.copy()
    nxt = next_reaction(frame, reactions)
    week = (nxt >= 0) & (nxt <= frame["position"].to_numpy() + HORIZON_DAYS)
    frame["earnings_week"] = week
    frame["reaction_date"] = pd.Series(calendar[np.where(week, nxt, 0)], index=frame.index).where(week)
    frame["earnings_J"] = jump_sizes(frame, panel, reactions)
    for name in skill_names:
        frame[f"own_pred_{name}"] = frame[f"pred_{name}"]
    return add_jump(frame, skill_names, frame["earnings_J"].to_numpy())
