"""FastAPI server exposing the engine's output in the shapes of /contracts (contract v2).

It serves what ``python -m tsm.backtest`` last produced, and only committed files:
``artifacts/predictions.csv``, ``artifacts/meta.json`` and ``artifacts/earnings.csv``
(the report dates behind ``earnings_date``). Nothing is trained or downloaded while
answering a request, and nothing reads ``algo/data/`` (prices, earnings), which a
fresh clone does not have.

Endpoints: ``/tickers``, ``/predict``, ``/history`` (v1) and ``/overview``,
``/weights``, ``/performance`` (v2). ``/performance`` is computed with the same
function that writes ``docs/backtest.md`` (``report.backtest_numbers``), so the two
always agree.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from tsm.config import ARTIFACTS_DIR, HORIZON_DAYS, SECTORS, TICKERS

app = FastAPI(title="Temporal Skills Market API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("ALGO_CORS_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _store() -> tuple[pd.DataFrame, dict]:
    path = ARTIFACTS_DIR / "predictions.csv"
    if not path.exists():
        raise HTTPException(status_code=503, detail="No predictions yet: run `python -m tsm.backtest` first.")
    frame = pd.read_csv(path, parse_dates=["date"])
    meta = json.loads((ARTIFACTS_DIR / "meta.json").read_text())
    return frame, meta


def clear_cache() -> None:
    """Forget everything read from the artifacts (tests point ARTIFACTS_DIR elsewhere)."""
    for cached in (_store, _report_dates, _performance):
        cached.cache_clear()


@lru_cache(maxsize=1)
def _report_dates() -> dict[tuple[str, str], str] | None:
    """(ticker, reaction date) -> the date the company published its report.

    None when the artifacts were built without the earnings layer: then the engine
    does not report ``earnings_date`` at all and the field is left out.
    """
    _, meta = _store()
    path = ARTIFACTS_DIR / "earnings.csv"
    if not meta.get("earnings", {}).get("enabled") or not path.exists():
        return None
    table = pd.read_csv(path, dtype=str)
    return dict(zip(zip(table["ticker"], table["reaction_date"]), table["report_date"]))


def _earnings(row) -> dict:
    """``{"earnings_date": ...}`` for a prediction row, or ``{}`` when the engine does not report it.

    The report date when the reaction to it falls in the 5 trading days the
    prediction covers (an earnings week), else null. For a report after the close
    the report date is the trading day before the reaction day.
    """
    dates = _report_dates()
    if dates is None:
        return {}
    if not bool(row["earnings_week"]):
        return {"earnings_date": None}
    return {"earnings_date": dates[(row["ticker"], str(row["reaction_date"]))]}


def _rows(ticker: str) -> tuple[pd.DataFrame, dict]:
    frame, meta = _store()
    ticker = ticker.strip().upper()
    rows = frame[frame["ticker"] == ticker]
    if ticker not in TICKERS or rows.empty:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return rows.sort_values("date"), meta


def _realized(value: float) -> float | None:
    return None if math.isnan(value) else float(value)


@app.get("/tickers")
def tickers() -> dict:
    frame, _ = _store()
    served = set(frame["ticker"])
    return {
        "tickers": [
            {"ticker": t, "name": name, **({"sector": SECTORS[t]} if t in SECTORS else {})}
            for t, name in TICKERS.items()
            if t in served
        ]
    }


@app.get("/predict")
def predict(ticker: str = Query(...)) -> dict:
    rows, meta = _rows(ticker)
    last = rows.iloc[-1]
    return {
        "ticker": last["ticker"],
        "as_of_date": last["date"].date().isoformat(),
        "horizon_days": HORIZON_DAYS,
        "predicted_vol": float(last["supervisor"]),
        "baseline_vol": float(last["baseline"]),
        "skills": [
            {
                "name": skill["name"],
                "horizon": skill["horizon"],
                "weight": float(last[f"w_{skill['name']}"]),
                "predicted_vol": float(last[f"pred_{skill['name']}"]),
            }
            for skill in meta["skills"]
        ],
        "supervisor_confidence": float(last["confidence"]),
        "model_version": meta["model_version"],
        **_earnings(last),
    }


@app.get("/history")
def history(ticker: str = Query(...)) -> dict:
    rows, _ = _rows(ticker)
    return {
        "ticker": rows["ticker"].iloc[0],
        "horizon_days": HORIZON_DAYS,
        "points": [
            {
                "as_of_date": row.date.date().isoformat(),
                "predicted_vol": float(row.supervisor),
                "baseline_vol": float(row.baseline),
                "realized_vol": _realized(row.realized_vol),
            }
            for row in rows.itertuples()
        ],
    }


@app.get("/overview")
def overview() -> dict:
    """One entry per ticker with a prediction: what the watchlist needs, in one request."""
    frame, _ = _store()
    entries = []
    for ticker, rows in frame.sort_values("date").groupby("ticker", sort=False):
        last = rows.iloc[-1]
        known = rows["realized_vol"].dropna()
        entries.append(
            {
                "ticker": ticker,
                "as_of_date": last["date"].date().isoformat(),
                "predicted_vol": float(last["supervisor"]),
                "baseline_vol": float(last["baseline"]),
                "supervisor_confidence": float(last["confidence"]),
                "latest_realized_vol": float(known.iloc[-1]) if len(known) else None,
                **_earnings(last),
            }
        )
    order = {t: i for i, t in enumerate(TICKERS)}
    return {"entries": sorted(entries, key=lambda e: order.get(e["ticker"], len(order)))}


@app.get("/weights")
def weights(ticker: str = Query(...)) -> dict:
    """The supervisor's weight per skill on every date of /history, oldest first."""
    rows, meta = _rows(ticker)
    names = [s["name"] for s in meta["skills"]]
    values = rows[[f"w_{n}" for n in names]].to_numpy(dtype=float)
    return {
        "ticker": rows["ticker"].iloc[0],
        "skills": [{"name": s["name"], "horizon": s["horizon"]} for s in meta["skills"]],
        "points": [
            {
                "as_of_date": day.date().isoformat(),
                "weights": [{"name": n, "weight": float(w)} for n, w in zip(names, row)],
            }
            for day, row in zip(rows["date"], values)
        ],
    }


@lru_cache(maxsize=1)
def _performance() -> dict:
    # Imported here: tsm.report loads every skill's library, which the other endpoints do not need.
    from tsm.report import BASELINE, backtest_numbers

    frame, meta = _store()
    numbers = backtest_numbers(frame, meta)
    table, rows, per_ticker = numbers["table"], numbers["rows"], numbers["per_ticker"]
    horizons = {s["name"]: s["horizon"] for s in meta["skills"]}

    def vs_har_rv(model: str, metric: str) -> float | None:
        return None if model == BASELINE else float(table.loc[model, f"{metric} vs HAR-RV"]) / 100

    models = []
    for model in table.index:
        kind = "supervisor" if model == "supervisor" else "skill" if model in horizons else "baseline"
        models.append(
            {
                "name": "har_rv" if model == BASELINE else model,
                "kind": kind,
                "rmse": float(table.loc[model, "RMSE"]),
                "mae": float(table.loc[model, "MAE"]),
                "qlike": float(table.loc[model, "QLIKE"]),
                "rmse_vs_har_rv": vs_har_rv(model, "RMSE"),
                "mae_vs_har_rv": vs_har_rv(model, "MAE"),
                "qlike_vs_har_rv": vs_har_rv(model, "QLIKE"),
            }
        )
    supervisor, baseline = float(table.loc["supervisor", "QLIKE"]), float(table.loc[BASELINE, "QLIKE"])
    return {
        "generated_at": meta.get("generated_at", meta["last_date"]),
        "model_version": meta["model_version"],
        "period_start": rows["date"].min().date().isoformat(),
        "period_end": rows["date"].max().date().isoformat(),
        "evaluation_dates": int(rows["date"].nunique()),
        "scored_predictions": int(len(rows)),
        "tickers": [str(t) for t in rows["ticker"].unique()],
        "headline": {
            "metric": "qlike",
            "supervisor": supervisor,
            "baseline": baseline,
            "improvement": 1 - supervisor / baseline,
            "tickers_better": numbers["wins"],
            "tickers_total": int(len(per_ticker)),
            "t_statistic": float(numbers["tstat"]),
        },
        "models": models,
        "skill_weights": [
            {
                "name": name,
                "horizon": horizons[name],
                "mean": float(numbers["weights"].loc[f"w_{name}", "mean"]),
                "min": float(numbers["weights"].loc[f"w_{name}", "min"]),
                "max": float(numbers["weights"].loc[f"w_{name}", "max"]),
            }
            for name in numbers["skill_names"]
        ],
        "per_ticker": [
            {
                "ticker": str(ticker),
                "supervisor_qlike": float(row["supervisor"]),
                "baseline_qlike": float(row[BASELINE]),
            }
            for ticker, row in per_ticker.iterrows()
        ],
    }


@app.get("/performance")
def performance() -> dict:
    """The walk-forward backtest summary: the numbers of docs/backtest.md."""
    return _performance()
