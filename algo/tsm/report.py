"""Writes docs/backtest.md and its assets from the backtest's output. Never edit the report by hand."""
from __future__ import annotations

from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from tsm.config import DOCS_DIR, HORIZON_DAYS
from tsm.supervisor import qlike

BASELINE = "baseline"
LABELS = {
    "supervisor": "**Supervisor (the market)**",
    "baseline": "HAR-RV baseline (= skill `short_term`)",
    "naive": "Naive (last 5-day volatility)",
    "equal_weight": "Equal-weight average of the skills",
}


# Columns that describe a row rather than predict it, and are empty on purpose for most rows
# (reaction_date only exists in earnings weeks): a missing value there must not drop the row.
DESCRIPTIVE_COLUMNS = ("reaction_date",)

# The validation year: the last full year before the test period (backtest.TEST_START).
VALIDATION_START, VALIDATION_END = "2019-01-01", "2020-01-01"


def _complete(rows: pd.DataFrame) -> pd.DataFrame:
    return rows.dropna(subset=[c for c in rows.columns if c not in DESCRIPTIVE_COLUMNS])


def scored_rows(frame: pd.DataFrame, test_start: str) -> pd.DataFrame:
    """Test-period rows whose outcome is known. Every model is scored on exactly these."""
    rows = frame[(frame["date"] >= pd.Timestamp(test_start)) & frame["realized_vol"].notna()]
    return _complete(rows)


def validation_rows(frame: pd.DataFrame, start: str = VALIDATION_START, end: str = VALIDATION_END) -> pd.DataFrame:
    """Rows of the validation year whose outcome is known, picked the way ``scored_rows`` picks the test rows."""
    rows = frame[
        (frame["date"] >= pd.Timestamp(start)) & (frame["date"] < pd.Timestamp(end)) & frame["realized_vol"].notna()
    ]
    return _complete(rows)


def week_scores(frame: pd.DataFrame, columns: dict[str, str], test_start: str = VALIDATION_END) -> pd.DataFrame:
    """QLIKE per model: test, 2019, and test split into earnings weeks and ordinary weeks.

    ``frame`` needs an ``earnings_week`` column; ``columns`` maps model -> column.
    """
    test, val = scored_rows(frame, test_start), validation_rows(frame, end=test_start)
    week = test["earnings_week"].astype(bool)
    table = {}
    for model, column in columns.items():
        loss = qlike(test["realized_vol"], test[column])
        table[model] = {
            "QLIKE": loss.mean(),
            "QLIKE_2019": qlike(val["realized_vol"], val[column]).mean(),
            "QLIKE_earnings": loss[week].mean(),
            "QLIKE_ordinary": loss[~week].mean(),
        }
    out = pd.DataFrame(table).T
    out.attrs["earnings_share"] = float(week.mean())
    return out


def model_columns(skill_names: list[str], plain_baseline: bool = False) -> dict[str, str]:
    """Report row -> column of the frame, in display order.

    Without the earnings layer the baseline is the skill ``short_term`` itself,
    so that skill gets no row of its own; with it (``plain_baseline``) the skill
    carries the earnings jump and the baseline does not, so both are shown.
    """
    columns = {"supervisor": "supervisor", "baseline": "baseline"}
    columns.update({s: f"pred_{s}" for s in skill_names if plain_baseline or f"pred_{s}" != "pred_short_term"})
    columns.update({"naive": "naive", "equal_weight": "equal_weight"})
    return columns


def metrics_table(rows: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    realized = rows["realized_vol"]
    table = pd.DataFrame(
        {
            "RMSE": {m: np.sqrt(((rows[c] - realized) ** 2).mean()) for m, c in columns.items()},
            "MAE": {m: (rows[c] - realized).abs().mean() for m, c in columns.items()},
            "QLIKE": {m: qlike(realized, rows[c]).mean() for m, c in columns.items()},
        }
    )
    for metric in ("RMSE", "MAE", "QLIKE"):
        table[f"{metric} vs HAR-RV"] = 100 * (1 - table[metric] / table.loc[BASELINE, metric])
    return table


def loss_difference_tstat(rows: pd.DataFrame, lags: int = HORIZON_DAYS) -> float:
    """t-statistic of (HAR-RV QLIKE - supervisor QLIKE), averaged over tickers per date.

    Newey-West correction, because 5-day windows of consecutive dates overlap.
    Above about 2 means the difference is unlikely to be luck.
    """
    diff = (qlike(rows["realized_vol"], rows["baseline"]) - qlike(rows["realized_vol"], rows["supervisor"]))
    d = diff.groupby(rows["date"]).mean().to_numpy()
    n = len(d)
    centered = d - d.mean()
    variance = centered @ centered / n
    for lag in range(1, lags + 1):
        variance += 2 * (1 - lag / (lags + 1)) * (centered[lag:] @ centered[:-lag]) / n
    return float(d.mean() / np.sqrt(variance / n))


def _markdown_table(table: pd.DataFrame, labels: dict[str, str]) -> str:
    best = {m: table[m].idxmin() for m in ("RMSE", "MAE", "QLIKE")}
    lines = [
        "| Model | RMSE | MAE | QLIKE | RMSE vs HAR-RV | MAE vs HAR-RV | QLIKE vs HAR-RV |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, row in table.iterrows():
        cells = []
        for metric in ("RMSE", "MAE", "QLIKE"):
            text = f"{row[metric]:.4f}"
            cells.append(f"**{text}**" if best[metric] == model else text)
        cells += ["—" if model == BASELINE else f"{row[f'{m} vs HAR-RV']:+.1f}%" for m in ("RMSE", "MAE", "QLIKE")]
        lines.append(f"| {labels.get(model, f'Skill `{model}`')} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def calibration_table(rows: pd.DataFrame, skill_names: list[str]) -> str:
    """QLIKE of each skill on its raw predictions against its calibrated ones."""
    realized = rows["realized_vol"]
    lines = [
        "| Model | Mean factor | Mean raw bias | QLIKE before | QLIKE after | QLIKE change |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    raw_equal = rows[[f"raw_pred_{s}" for s in skill_names]].mean(axis=1)
    entries = [(f"Skill `{s}`", rows[f"raw_pred_{s}"], rows[f"pred_{s}"], rows[f"c_{s}"].mean()) for s in skill_names]
    entries.append((LABELS["equal_weight"], raw_equal, rows["equal_weight"], float("nan")))
    for label, raw, calibrated, factor in entries:
        before, after = qlike(realized, raw).mean(), qlike(realized, calibrated).mean()
        bias = (raw / realized).mean()
        factor_text = "—" if pd.isna(factor) else f"{factor:.3f}"
        lines.append(
            f"| {label} | {factor_text} | {bias:.3f} | {before:.4f} | {after:.4f} | "
            f"{100 * (1 - after / before):+.1f}% |"
        )
    return chr(10).join(lines)


# The predicted-vs-realized chart draws one panel per ticker, so it only shows these.
CHART_TICKERS = ["SPY", "AAPL", "NVDA", "TEVA", "JPM", "XOM"]


def _charts(rows: pd.DataFrame, table: pd.DataFrame, skill_names: list[str], assets) -> None:
    available = set(rows["ticker"].unique())
    # Fall back to whatever is there, so the chart also works on a panel of other tickers.
    tickers = [t for t in CHART_TICKERS if t in available] or sorted(available)[:len(CHART_TICKERS)]
    fig, axes = plt.subplots(len(tickers), 1, figsize=(11, 2.2 * len(tickers)), sharex=True)
    for ax, ticker in zip(np.atleast_1d(axes), tickers):
        one = rows[rows["ticker"] == ticker].iloc[::HORIZON_DAYS]
        ax.plot(one["date"], one["realized_vol"], color="0.6", lw=0.8, label="realized")
        ax.plot(one["date"], one["baseline"], color="tab:orange", lw=0.8, label="HAR-RV")
        ax.plot(one["date"], one["supervisor"], color="tab:blue", lw=0.8, label="supervisor")
        ax.set_ylabel(ticker)
        ax.set_ylim(0, one["realized_vol"].quantile(0.995) * 1.1)
    np.atleast_1d(axes)[0].legend(ncol=3, loc="upper right", fontsize=8)
    fig.suptitle("Predicted vs realized 5-day volatility (annualized, one point per week)"
                 f" - {len(tickers)} of {len(available)} tickers")
    fig.tight_layout()
    fig.savefig(assets / "predicted_vs_realized.png", dpi=110)
    plt.close(fig)

    weights = rows.groupby("date")[[f"w_{s}" for s in skill_names]].mean().rolling(20, min_periods=1).mean()
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.stackplot(weights.index, weights.to_numpy().T, labels=skill_names)
    ax.set_ylim(0, 1)
    ax.set_title("Supervisor weights over time (average over tickers, 20-day smoothing)")
    ax.legend(ncol=len(skill_names), loc="lower center", fontsize=8)
    fig.tight_layout()
    fig.savefig(assets / "weights_over_time.png", dpi=110)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 3.5))
    ordered = table["QLIKE"].sort_values()
    colors = ["tab:blue" if m == "supervisor" else "tab:orange" if m == BASELINE else "0.6" for m in ordered.index]
    ax.barh([m.replace("baseline", "HAR-RV baseline") for m in ordered.index], ordered.to_numpy(), color=colors)
    ax.invert_yaxis()
    ax.set_title("QLIKE per model (lower is better)")
    fig.tight_layout()
    fig.savefig(assets / "qlike_per_model.png", dpi=110)
    plt.close(fig)


def earnings_section(earnings: dict, skill_names: list[str]) -> str:
    """The "Earnings layer" section: before/after by kind of week, the placebo, the assumption."""
    before, after = earnings["before"], earnings["after"]
    names = {"supervisor": "Supervisor", "equal_weight": "Equal-weight", "baseline": "HAR-RV baseline (plain)"}
    lines = [
        "| Model | QLIKE without | QLIKE with | Earnings weeks without | Earnings weeks with "
        "| Ordinary weeks without | Ordinary weeks with |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in ("supervisor", "equal_weight", *skill_names, "baseline"):
        b, a = before.loc[model], after.loc[model]
        lines.append(
            f"| {names.get(model, f'Skill `{model}`')} | {b['QLIKE']:.4f} | {a['QLIKE']:.4f} | "
            f"{b['QLIKE_earnings']:.4f} | {a['QLIKE_earnings']:.4f} | {b['QLIKE_ordinary']:.4f} | {a['QLIKE_ordinary']:.4f} |"
        )
    placebo = ", ".join(
        f"{q:.4f} with the dates {abs(s)} trading days {'later' if s > 0 else 'earlier'}"
        for s, q in earnings["placebo"].items()
    )
    return f"""## Earnings layer

In an earnings week (a forecast whose next 5 trading days contain an earnings reaction day) every skill's
predicted variance gets one expected earnings move before calibration: `vol = sqrt(vol^2 + 252/5 * J)`, with
`J` the ticker's average excess squared return on its past reaction days (only those already known on the
forecast day), shrunk toward the average over all tickers. The HAR-RV baseline stays plain HAR-RV, calibrated,
without the jump, so every "vs HAR-RV" number stays comparable with earlier reports.

**Assumption:** release dates, and whether they come before the open or after the close, are known at least 5
trading days ahead (companies announce them weeks ahead). They come from Yahoo Finance and were checked against
SEC filings (`tsm/earnings.py`).

Earnings weeks are {after.attrs['earnings_share']:.1%} of the scored forecasts. QLIKE without and with the layer
(the same weeks, the same skills, the supervisor retuned each time):

{chr(10).join(lines)}

**Placebo:** with every reaction day moved by 20 trading days, the supervisor scores {placebo}, against
{before.loc['supervisor', 'QLIKE']:.4f} without the layer and {after.loc['supervisor', 'QLIKE']:.4f} with it. The gain
comes from the real earnings dates, not from the mechanism.
"""


def backtest_numbers(frame: pd.DataFrame, meta: dict) -> dict:
    """Every number the report states, computed once.

    ``write_report`` writes them into docs/backtest.md and the API's ``/performance``
    serves them, so the two can never disagree. Keys: ``columns`` (model -> frame
    column), ``rows`` (the scored rows), ``table`` (RMSE, MAE, QLIKE and their % vs
    HAR-RV per model), ``tstat``, ``per_ticker`` (QLIKE per ticker and model, in the
    order the tickers appear), ``wins`` (tickers where the supervisor beats HAR-RV)
    and ``weights`` (mean, min and max weight per skill).
    """
    skill_names = [s["name"] for s in meta["skills"]]
    with_earnings = bool(meta.get("earnings", {}).get("enabled"))
    columns = model_columns(skill_names, plain_baseline=with_earnings)
    rows = scored_rows(frame, meta["test_start"])
    # Per-ticker QLIKE: on how many tickers does the supervisor beat the baseline?
    per_ticker = rows.groupby("ticker").apply(
        lambda g: pd.Series({m: qlike(g["realized_vol"], g[c]).mean() for m, c in columns.items()}),
        include_groups=False,
    )
    order = rows["ticker"].unique()
    return {
        "skill_names": skill_names,
        "with_earnings": with_earnings,
        "columns": columns,
        "rows": rows,
        "table": metrics_table(rows, columns),
        "tstat": loss_difference_tstat(rows),
        "per_ticker": per_ticker.loc[order],
        "wins": int((per_ticker["supervisor"] < per_ticker[BASELINE]).sum()),
        "weights": rows[[f"w_{s}" for s in skill_names]].agg(["mean", "min", "max"]).T,
    }


def write_report(frame: pd.DataFrame, meta: dict, docs_dir=DOCS_DIR, earnings: dict | None = None) -> pd.DataFrame:
    """Write docs/backtest.md, results.csv, weights.csv and the charts. Returns the metrics table.

    ``earnings`` is the before/after comparison of the earnings layer (``backtest.earnings_comparison``);
    with it the report gains an "Earnings layer" section.
    """
    assets = docs_dir / "backtest_assets"
    assets.mkdir(parents=True, exist_ok=True)
    numbers = backtest_numbers(frame, meta)
    skill_names, with_earnings, columns = numbers["skill_names"], numbers["with_earnings"], numbers["columns"]
    rows, table, tstat = numbers["rows"], numbers["table"], numbers["tstat"]
    per_ticker, wins = numbers["per_ticker"], numbers["wins"]
    labels = dict(LABELS)
    if with_earnings:
        labels["baseline"] = "HAR-RV baseline (plain `short_term`, no earnings jump)"

    results = rows.melt(
        id_vars=["date", "ticker", "realized_vol"], value_vars=list(columns.values()),
        var_name="model", value_name="predicted_vol",
    )
    results["model"] = results["model"].str.removeprefix("pred_")
    results.to_csv(assets / "results.csv", index=False, float_format="%.6f")
    weight_columns = [f"w_{s}" for s in skill_names]
    rows[["date", "ticker", *weight_columns]].to_csv(assets / "weights.csv", index=False, float_format="%.6f")
    _charts(rows, table, skill_names, assets)

    gain = table.loc["supervisor", "QLIKE vs HAR-RV"]
    gain_rmse = table.loc["supervisor", "RMSE vs HAR-RV"]
    best = table["QLIKE"].idxmin()
    verdict = "beats" if gain > 0 else "does not beat"
    certainty = (
        "The difference is statistically solid" if abs(tstat) >= 2
        else "The difference is too small to rule out luck"
    )
    summary = (
        f"The supervisor {verdict} the HAR-RV baseline on QLIKE: {table.loc['supervisor', 'QLIKE']:.4f} "
        f"against {table.loc[BASELINE, 'QLIKE']:.4f} ({gain:+.1f}%), and {gain_rmse:+.1f}% on RMSE. "
        f"It is better than HAR-RV on {wins} of {per_ticker.shape[0]} tickers. "
        f"{certainty} (t-statistic {tstat:.2f}; about 2 or more is the usual bar). "
    )
    if best != "supervisor":
        summary += (
            f"The best model on QLIKE is {LABELS.get(best, f'the skill `{best}`').replace('**', '')}, "
            f"not the supervisor. "
        )
    eq_gain = 100 * (1 - table.loc["supervisor", "QLIKE"] / table.loc["equal_weight", "QLIKE"])
    summary += (
        f"Against a plain equal-weight average of the same skills, the supervisor's dynamic weighting "
        f"changes QLIKE by {eq_gain:+.1f}% (positive = the weighting helps)."
    )

    weight_stats = numbers["weights"]
    weight_lines = ["| Skill | Horizon | Mean weight | Min | Max |", "| --- | --- | ---: | ---: | ---: |"]
    horizons = {s["name"]: s["horizon"] for s in meta["skills"]}
    for name in skill_names:
        w = weight_stats.loc[f"w_{name}"]
        weight_lines.append(f"| `{name}` | {horizons[name]} | {w['mean']:.3f} | {w['min']:.3f} | {w['max']:.3f} |")
    by_ticker = rows.groupby("ticker", sort=False)[weight_columns].mean()
    ticker_lines = ["| Ticker | " + " | ".join(f"`{s}`" for s in skill_names) + " | Supervisor QLIKE | HAR-RV QLIKE |",
                    "| --- | " + " | ".join("---:" for _ in skill_names) + " | ---: | ---: |"]
    for ticker, w in by_ticker.iterrows():
        ticker_lines.append(
            f"| {ticker} | " + " | ".join(f"{v:.3f}" for v in w) +
            f" | {per_ticker.loc[ticker, 'supervisor']:.4f} | {per_ticker.loc[ticker, BASELINE]:.4f} |"
        )

    n_dates = rows["date"].nunique()
    tickers = ", ".join(rows["ticker"].unique())
    calibration = calibration_table(rows, skill_names)
    calibration_window = meta["calibration_window"]
    n_skills = len(skill_names)
    n_tickers = rows["ticker"].nunique()
    if with_earnings:
        baseline_note = (
            "The baseline is the skill `short_term` without the earnings jump; the `short_term` row has it."
        )
        calibration_note = (
            " With the earnings layer on, \"QLIKE after\" includes the earnings jump as well as the calibration;"
            " \"QLIKE before\" is each model's own prediction."
        )
        earnings_caveat = (
            "\n- The earnings layer assumes release dates (and their time of day) are known 5 trading days ahead, and"
            " takes them from Yahoo Finance, an unofficial source. A ticker with no scheduled date in the saved file"
            " gets no earnings week in its latest forecasts."
        )
    else:
        baseline_note = "The skill `short_term` is the HAR-RV model, so it and the baseline are one and the same row."
        calibration_note = earnings_caveat = ""
    earnings_text = "\n" + earnings_section(earnings, skill_names) if earnings is not None else ""
    text = f"""# Backtest report

Generated by `python -m tsm.backtest`. Do not edit by hand.

## Summary

{summary}

## Setup

- **Tickers ({rows['ticker'].nunique()}):** {tickers}
- **Test period:** {rows['date'].min().date()} to {rows['date'].max().date()}, {n_dates} evaluation dates (every trading day), {len(rows)} scored predictions.
- **Target:** annualized 5-trading-day realized volatility, as defined in `contracts/README.md`.
- **Method:** walk-forward. On each date every skill sees only prices up to that date. Skills start predicting on {frame['date'].min().date()}; the dates before {meta['test_start']} are used only to choose the supervisor's two settings and are not scored here.
- **Supervisor settings:** window of {meta['supervisor']['window']} past predictions, softmax temperature {meta['supervisor']['temperature']}.
- **Model version:** {meta['model_version']}. **Report generated:** {date.today().isoformat()}. **Last price date:** {meta['last_date']}.

## Metrics vs baselines

Lower is better for all three metrics. The "vs HAR-RV" columns are the improvement over the baseline (positive = better than HAR-RV). Best value per column in bold.

{_markdown_table(table, labels)}

{baseline_note}

## Before vs after calibration

Every skill's prediction is multiplied by a factor `c = sqrt(mean((realized / predicted)^2))`, recomputed
each day from the last {calibration_window} trading days of predictions whose 5-day outcome was already known on that
day, pooled over tickers. A factor above 1 scales the skill's predictions up.

The two diagnostic columns measure different things, and both can sit above 1 at the same time:

- **Mean raw bias** is the plain average of predicted / realized. Above 1 means the skill reads high on a typical day.
- **Mean factor** is driven by the average of `(realized / predicted)^2`, which is dominated by the few days when
  realized volatility ran far past the prediction.

So a skill can read slightly high on most days and still fall badly short during volatility spikes. QLIKE punishes
exactly those spikes, which is why scaling up still pays: it trades a little everyday over-prediction for much better
coverage of the tail. The HAR-RV baseline is the calibrated `short_term` row, so the comparison in the table above is
between calibrated models.

{calibration}

The equal-weight row has no single factor of its own; it averages the {n_skills} calibrated skills.{calibration_note}
{earnings_text}
## Average weight per skill

{chr(10).join(weight_lines)}

Per ticker (mean weight of each skill, and QLIKE of the supervisor against HAR-RV):

{chr(10).join(ticker_lines)}

## Charts

![Predicted vs realized volatility](backtest_assets/predicted_vs_realized.png)

![Supervisor weights over time](backtest_assets/weights_over_time.png)

![QLIKE per model](backtest_assets/qlike_per_model.png)

## Caveats

- {n_tickers} large, liquid US-listed names over one period that includes the 2020 crash. Results may not carry over to other stocks or calmer or wilder periods.
- The universe was picked by size as of today, so it only contains companies that survived and grew into the index. Any company that shrank, was acquired or went bankrupt over the period is absent. This survivorship bias flatters every model here, including the baselines, and it is not corrected anywhere in this report.
- Consecutive evaluation dates share 4 of their 5 target days, so the {len(rows)} scored predictions are far from independent. The t-statistic above corrects for this; the raw count overstates the evidence.
- "Realized volatility" here comes from 5 daily closing prices, which is itself a noisy measure of true volatility. Part of every model's error is noise in the target.
- The supervisor's window and temperature were chosen once, on predictions from before {meta['test_start']}, and not touched afterwards. The skills' own settings (network size, tree depth, feature windows) were fixed by hand and not tuned.
- The skill `itransformer` (our own PyTorch iTransformer, the mean of three seeds) is deliberately small (hidden size 64, 300 training steps, retrained every 125 trading days) to keep the run short on CPU. A larger network might do better or worse; this was not explored. The seeds are averaged because a single seed moved its test QLIKE by up to 0.005 in `docs/experiments.md`.
- Every skill is rescaled each day by the calibration factor described above. The factor is itself estimated from {calibration_window} days of noisy outcomes, so it carries estimation error, and it is a single number per skill: it removes an average bias but cannot fix a skill whose bias varies with the level of volatility.
- Prices are adjusted for splits and dividends as of the download date.{earnings_caveat}
"""
    (docs_dir / "backtest.md").write_text(text, encoding="utf-8")
    return table
