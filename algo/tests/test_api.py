"""Every endpoint must return exactly the shapes of /contracts/prediction.schema.json."""
import json

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException

from tsm import api

from tests.test_contract import validator

SKILLS = [
    {"name": "short_term", "horizon": "short"},
    {"name": "regime", "horizon": "long"},
    {"name": "weak_signals", "horizon": "short"},
    {"name": "multivariate", "horizon": "medium"},
]


@pytest.fixture(autouse=True)
def artifacts(tmp_path, monkeypatch):
    """A small predictions file in the format the backtest writes."""
    rows = []
    for ticker in ("AAPL", "SPY"):
        for i, day in enumerate(pd.bdate_range("2026-09-01", periods=8)):
            row = {"date": day, "ticker": ticker, "position": i, "realized_vol": 0.2 if i < 3 else np.nan}
            for skill in SKILLS:
                row[f"pred_{skill['name']}"] = 0.2 + 0.01 * i
                row[f"w_{skill['name']}"] = 0.25
            row.update(naive=0.2, equal_weight=0.21, baseline=0.22, supervisor=0.23, confidence=0.7)
            rows.append(row)
    pd.DataFrame(rows).to_csv(tmp_path / "predictions.csv", index=False)
    (tmp_path / "meta.json").write_text(json.dumps({"model_version": "0.0.0-test", "skills": SKILLS}))
    monkeypatch.setattr(api, "ARTIFACTS_DIR", tmp_path)
    api._store.cache_clear()
    yield
    api._store.cache_clear()


def test_predict_matches_contract():
    body = api.predict(ticker="AAPL")
    validator("Prediction").validate(body)
    assert body["ticker"] == "AAPL"
    assert body["as_of_date"] == "2026-09-10"  # the latest date
    assert sum(s["weight"] for s in body["skills"]) == pytest.approx(1)
    assert [s["name"] for s in body["skills"]] == [s["name"] for s in SKILLS]


def test_predict_accepts_lower_case():
    assert api.predict(ticker="aapl")["ticker"] == "AAPL"


def test_tickers_matches_contract():
    body = api.tickers()
    validator("TickersResponse").validate(body)
    assert [t["ticker"] for t in body["tickers"]] == ["AAPL", "SPY"]


def test_history_matches_contract():
    body = api.history(ticker="SPY")
    validator("HistoryResponse").validate(body)
    points = body["points"]
    assert len(points) == 8
    assert [p["as_of_date"] for p in points] == sorted(p["as_of_date"] for p in points)
    assert points[0]["realized_vol"] == pytest.approx(0.2)
    assert points[-1]["realized_vol"] is None  # outcome not known yet
    json.dumps(body, allow_nan=False)  # no NaN may reach the JSON


@pytest.mark.parametrize("endpoint", [api.predict, api.history])
def test_unknown_ticker_is_404(endpoint):
    with pytest.raises(HTTPException) as error:
        endpoint(ticker="NOPE")
    assert error.value.status_code == 404
    validator("Error").validate({"detail": error.value.detail})


def test_registered_routes():
    paths = {route.path for route in api.app.routes}
    assert {"/predict", "/tickers", "/history"} <= paths
