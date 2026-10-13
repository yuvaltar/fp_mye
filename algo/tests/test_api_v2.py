"""Contract v2 endpoints on small synthetic artifacts: /overview, /weights, /performance,
`sector` on /tickers and `earnings_date` on /predict and /overview."""
import json

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from tsm import api
from tsm.config import SECTORS
from tsm.report import BASELINE, backtest_numbers

from tests.test_contract import validator

SKILLS = [
    {"name": "short_term", "horizon": "short"},
    {"name": "regime", "horizon": "long"},
    {"name": "weak_signals", "horizon": "short"},
    {"name": "itransformer", "horizon": "medium"},
]
DAYS = pd.bdate_range("2026-01-02", periods=40)
AS_OF = DAYS[-1]
# AAPL reports after the close the next trading day, so it reacts the trading day after that:
# the prediction made on AS_OF covers the reaction, and earnings_date is the report day.
AAPL_REPORT, AAPL_REACTION = AS_OF + pd.offsets.BDay(1), AS_OF + pd.offsets.BDay(2)
JPM_REPORT = JPM_REACTION = DAYS[20]  # an earlier earnings week, before the open


def frame() -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for ticker in ("AAPL", "JPM", "SPY"):
        for i, day in enumerate(DAYS):
            weights = rng.dirichlet(np.ones(len(SKILLS)))
            row = {
                "date": day, "ticker": ticker, "position": 300 + i,
                "realized_vol": 0.2 * np.exp(rng.normal(0, 0.3)) if i < len(DAYS) - 5 else np.nan,
                "naive": 0.2 * np.exp(rng.normal(0, 0.3)), "confidence": 0.7,
                "earnings_week": False, "reaction_date": np.nan, "earnings_J": 0.0,
            }
            for skill, weight in zip(SKILLS, weights):
                row[f"pred_{skill['name']}"] = 0.2 * np.exp(rng.normal(0, 0.2))
                row[f"w_{skill['name']}"] = weight
            row["equal_weight"] = np.mean([row[f"pred_{s['name']}"] for s in SKILLS])
            row["baseline"] = 0.2 * np.exp(rng.normal(0, 0.25))
            row["supervisor"] = sum(row[f"pred_{s['name']}"] * row[f"w_{s['name']}"] for s in SKILLS)
            if ticker == "AAPL" and day == AS_OF:
                row.update(earnings_week=True, reaction_date=AAPL_REACTION.date().isoformat())
            if ticker == "JPM" and DAYS[15] <= day < DAYS[20]:
                row.update(earnings_week=True, reaction_date=JPM_REACTION.date().isoformat())
            rows.append(row)
    return pd.DataFrame(rows)


def write(path, earnings_enabled=True):
    frame().to_csv(path / "predictions.csv", index=False, float_format="%.6f")
    meta = {
        "model_version": "0.0.0-test", "skills": SKILLS, "supervisor": {"window": 20, "temperature": 0.25},
        "test_start": "2026-01-01", "calibration_window": 250, "last_date": AS_OF.date().isoformat(),
        "generated_at": "2026-03-01", "earnings": {"enabled": earnings_enabled},
    }
    (path / "meta.json").write_text(json.dumps(meta))
    pd.DataFrame(
        {
            "ticker": ["AAPL", "JPM"],
            "report_date": [AAPL_REPORT.date().isoformat(), JPM_REPORT.date().isoformat()],
            "reaction_date": [AAPL_REACTION.date().isoformat(), JPM_REACTION.date().isoformat()],
        }
    ).to_csv(path / "earnings.csv", index=False)


@pytest.fixture(autouse=True)
def artifacts(tmp_path, monkeypatch):
    write(tmp_path)
    monkeypatch.setattr(api, "ARTIFACTS_DIR", tmp_path)
    api.clear_cache()
    yield tmp_path
    api.clear_cache()


def test_the_v2_routes_are_registered():
    assert {"/overview", "/weights", "/performance"} <= {route.path for route in api.app.routes}


def test_tickers_carry_their_sector():
    body = api.tickers()
    validator("TickersResponse").validate(body)
    assert {t["ticker"]: t["sector"] for t in body["tickers"]} == {t: SECTORS[t] for t in ("AAPL", "JPM", "SPY")}


def test_earnings_date_is_the_report_day_not_the_reaction_day():
    body = api.predict(ticker="AAPL")
    validator("Prediction").validate(body)
    assert body["earnings_date"] == AAPL_REPORT.date().isoformat()
    assert body["earnings_date"] != AAPL_REACTION.date().isoformat()  # after the close: one trading day apart
    assert api.predict(ticker="JPM")["earnings_date"] is None  # its earnings week is over
    assert api.predict(ticker="SPY")["earnings_date"] is None


def test_earnings_date_is_left_out_when_the_engine_has_no_earnings_layer(artifacts):
    write(artifacts, earnings_enabled=False)
    api.clear_cache()
    assert "earnings_date" not in api.predict(ticker="AAPL")
    assert all("earnings_date" not in e for e in api.overview()["entries"])
    validator("OverviewResponse").validate(api.overview())


def test_overview_agrees_with_predict_and_history():
    body = api.overview()
    validator("OverviewResponse").validate(body)
    json.dumps(body, allow_nan=False)
    assert [e["ticker"] for e in body["entries"]] == ["AAPL", "JPM", "SPY"]  # /tickers order
    for entry in body["entries"]:
        prediction, history = api.predict(ticker=entry["ticker"]), api.history(ticker=entry["ticker"])
        for field in ("as_of_date", "predicted_vol", "baseline_vol", "supervisor_confidence", "earnings_date"):
            assert entry[field] == prediction[field]
        known = [p["realized_vol"] for p in history["points"] if p["realized_vol"] is not None]
        assert entry["latest_realized_vol"] == known[-1]


def test_weights_follow_history_sum_to_one_and_end_at_predict():
    body = api.weights(ticker="AAPL")
    validator("WeightsHistoryResponse").validate(body)
    history = api.history(ticker="AAPL")
    assert [p["as_of_date"] for p in body["points"]] == [p["as_of_date"] for p in history["points"]]
    for point in body["points"]:
        assert sum(w["weight"] for w in point["weights"]) == pytest.approx(1.0, abs=1e-5)  # CSV keeps 6 decimals
    prediction = api.predict(ticker="AAPL")
    assert body["points"][-1]["weights"] == [{"name": s["name"], "weight": s["weight"]} for s in prediction["skills"]]
    assert body["skills"] == [{"name": s["name"], "horizon": s["horizon"]} for s in SKILLS]


def test_unknown_ticker_is_404_for_weights():
    with pytest.raises(HTTPException) as error:
        api.weights(ticker="NOPE")
    assert error.value.status_code == 404
    validator("Error").validate({"detail": error.value.detail})


def test_performance_is_the_reports_own_numbers(artifacts):
    body = api.performance()
    validator("PerformanceResponse").validate(body)
    json.dumps(body, allow_nan=False)
    saved = pd.read_csv(artifacts / "predictions.csv", parse_dates=["date"])
    meta = json.loads((artifacts / "meta.json").read_text())
    numbers = backtest_numbers(saved, meta)
    table = numbers["table"]
    models = {m["name"]: m for m in body["models"]}
    assert list(models) == ["supervisor", "har_rv", "short_term", "regime", "weak_signals", "itransformer",
                            "naive", "equal_weight"]
    assert models["har_rv"]["kind"] == "baseline" and models["short_term"]["kind"] == "skill"
    assert models["supervisor"]["kind"] == "supervisor" and models["naive"]["kind"] == "baseline"
    assert all(models["har_rv"][f"{m}_vs_har_rv"] is None for m in ("rmse", "mae", "qlike"))
    assert models["har_rv"]["qlike"] == pytest.approx(table.loc[BASELINE, "QLIKE"])
    assert models["regime"]["qlike_vs_har_rv"] == pytest.approx(table.loc["regime", "QLIKE vs HAR-RV"] / 100)
    headline = body["headline"]
    assert headline["improvement"] == pytest.approx(1 - headline["supervisor"] / headline["baseline"])
    assert headline["t_statistic"] == pytest.approx(numbers["tstat"])
    assert headline["tickers_better"] == numbers["wins"] and headline["tickers_total"] == 3
    assert body["generated_at"] == "2026-03-01" and body["scored_predictions"] == 3 * (len(DAYS) - 5)
    assert [s["name"] for s in body["skill_weights"]] == [s["name"] for s in SKILLS]


def test_without_the_earnings_layer_short_term_is_the_baseline_row(artifacts):
    write(artifacts, earnings_enabled=False)
    api.clear_cache()
    names = [m["name"] for m in api.performance()["models"]]
    assert "har_rv" in names and "short_term" not in names
