"""The API on the committed artifacts, as a fresh clone serves it.

- /performance states exactly the numbers of docs/backtest.md (the report prints rounded
  numbers; the API, reading predictions.csv with 6 decimals, must round to the same).
- Every endpoint works without algo/data/ (prices, earnings), which is git-ignored.
- earnings_date can be given for every earnings week in predictions.csv.
"""
import re

import pandas as pd
import pytest

from tsm import api
from tsm.config import ARTIFACTS_DIR, DOCS_DIR

from tests.test_contract import validator

REPORT = (DOCS_DIR / "backtest.md").read_text(encoding="utf-8")
LABELS = {
    "**Supervisor (the market)**": "supervisor",
    "HAR-RV baseline (plain `short_term`, no earnings jump)": "har_rv",
    "HAR-RV baseline (= skill `short_term`)": "har_rv",
    "Naive (last 5-day volatility)": "naive",
    "Equal-weight average of the skills": "equal_weight",
}


@pytest.fixture(autouse=True)
def published():
    api.clear_cache()  # the real artifacts, whatever another test pointed the API at
    yield
    api.clear_cache()


def same(value: float, printed: str) -> bool:
    """``value`` rounds to the number the report printed.

    The report computes from the run's full-precision predictions, the API from
    predictions.csv, which keeps 6 decimals: allow that rounding on top of the
    printed precision (one per-ticker number, FCX's HAR-RV QLIKE 0.41465, sits on
    the rounding boundary).
    """
    decimals = len(printed.split(".")[1]) if "." in printed else 0
    return abs(value - float(printed)) <= 0.5 * 10 ** -decimals + 1e-6


def section(title: str) -> str:
    return REPORT.split(f"## {title}")[1].split("\n## ")[0]


def table_rows(text: str) -> list[list[str]]:
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in text.splitlines() if line.startswith("| ")]
    return [r for r in rows if not set(r[0]) <= {"-"} and r[0] not in ("Model", "Skill", "Ticker")]


def test_performance_states_the_numbers_of_the_published_report():
    body = api.performance()
    validator("PerformanceResponse").validate(body)
    headline = body["headline"]

    supervisor, baseline, gain = re.search(r"QLIKE: (\d\.\d{4}) against (\d\.\d{4}) \(([+-]\d+\.\d)%\)", REPORT).groups()
    assert same(headline["supervisor"], supervisor) and same(headline["baseline"], baseline)
    assert same(100 * headline["improvement"], gain.lstrip("+"))
    better, total = re.search(r"better than HAR-RV on (\d+) of (\d+) tickers", REPORT).groups()
    assert (headline["tickers_better"], headline["tickers_total"]) == (int(better), int(total))
    assert same(headline["t_statistic"], re.search(r"t-statistic (-?\d+\.\d{2})", REPORT).group(1))

    start, end, dates, scored = re.search(
        r"\*\*Test period:\*\* (\S+) to (\S+), (\d+) evaluation dates .*?, (\d+) scored predictions", REPORT
    ).groups()
    assert (body["period_start"], body["period_end"]) == (start, end)
    assert (body["evaluation_dates"], body["scored_predictions"]) == (int(dates), int(scored))
    tickers = re.search(r"\*\*Tickers \((\d+)\):\*\* (.+)", REPORT).group(2).split(", ")
    assert body["tickers"] == tickers
    assert body["model_version"] == re.search(r"\*\*Model version:\*\* (\S+)\.", REPORT).group(1)
    assert body["generated_at"] == re.search(r"\*\*Report generated:\*\* (\S+)\.", REPORT).group(1)

    models = {m["name"]: m for m in body["models"]}
    printed = table_rows(section("Metrics vs baselines"))
    assert len(printed) == len(models)
    for label, rmse, mae, qlike, *gains in printed:
        name = LABELS.get(label) or re.fullmatch(r"Skill `(\w+)`", label).group(1)
        model = models[name]
        for key, text in (("rmse", rmse), ("mae", mae), ("qlike", qlike)):
            assert same(model[key], text.strip("*")), (name, key)
        for key, text in zip(("rmse_vs_har_rv", "mae_vs_har_rv", "qlike_vs_har_rv"), gains):
            if text == "—":
                assert model[key] is None
            else:
                assert same(100 * model[key], text.rstrip("%").lstrip("+")), (name, key)

    weights = {w["name"]: w for w in body["skill_weights"]}
    for name, horizon, mean, low, high in table_rows(section("Average weight per skill").split("Per ticker")[0]):
        w = weights[name.strip("`")]
        assert w["horizon"] == horizon and same(w["mean"], mean) and same(w["min"], low) and same(w["max"], high)

    per_ticker = {p["ticker"]: p for p in body["per_ticker"]}
    printed = table_rows(section("Average weight per skill").split("Per ticker")[1])
    assert [r[0] for r in printed] == [p["ticker"] for p in body["per_ticker"]]
    for row in printed:
        assert same(per_ticker[row[0]]["supervisor_qlike"], row[-2]) and same(per_ticker[row[0]]["baseline_qlike"], row[-1])


def test_a_fresh_clone_serves_every_endpoint_without_algo_data(monkeypatch):
    """Nothing may read prices or earnings files, which a clone does not have."""
    import tsm.data
    import tsm.earnings

    def missing(*args, **kwargs):
        raise AssertionError("the API read algo/data/, which a fresh clone does not have")

    monkeypatch.setattr(tsm.data, "load_prices", missing)
    monkeypatch.setattr(tsm.data, "load_panel", missing)
    monkeypatch.setattr(tsm.earnings, "load_earnings", missing)
    in_earnings_week = [e["ticker"] for e in api.overview()["entries"] if e.get("earnings_date")]
    assert in_earnings_week, "the published artifacts end in an earnings week for some ticker"
    for ticker in ("AAPL", in_earnings_week[0]):
        validator("Prediction").validate(api.predict(ticker=ticker))
        validator("HistoryResponse").validate(api.history(ticker=ticker))
        validator("WeightsHistoryResponse").validate(api.weights(ticker=ticker))
    validator("TickersResponse").validate(api.tickers())
    validator("OverviewResponse").validate(api.overview())
    validator("PerformanceResponse").validate(api.performance())


def test_every_earnings_week_has_a_report_date():
    """earnings.csv covers every reaction day predictions.csv refers to, and each report comes
    on the reaction day or before it (after the close, or on a weekend)."""
    frame = pd.read_csv(ARTIFACTS_DIR / "predictions.csv", usecols=["ticker", "earnings_week", "reaction_date"])
    weeks = frame[frame["earnings_week"]].drop_duplicates(["ticker", "reaction_date"])
    dates = pd.read_csv(ARTIFACTS_DIR / "earnings.csv")
    merged = weeks.merge(dates, on=["ticker", "reaction_date"], how="left", validate="one_to_one")
    assert merged["report_date"].notna().all()
    gap = (pd.to_datetime(merged["reaction_date"]) - pd.to_datetime(merged["report_date"])).dt.days
    assert gap.between(0, 4).all()  # same day, the next trading day (over a weekend at most), or Saturday -> Monday
    assert (gap > 0).any() and (gap == 0).any()
