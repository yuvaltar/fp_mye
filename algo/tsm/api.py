"""FastAPI server exposing the engine's output in the shapes of /contracts.

It serves what ``python -m tsm.backtest`` last produced (artifacts/predictions.csv):
training the skills takes minutes, so nothing is trained while answering a request.
"""
from __future__ import annotations

import json
import math
import os
from functools import lru_cache

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from tsm.config import ARTIFACTS_DIR, HORIZON_DAYS, TICKERS

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


def _rows(ticker: str) -> tuple[pd.DataFrame, dict]:
    frame, meta = _store()
    ticker = ticker.strip().upper()
    rows = frame[frame["ticker"] == ticker]
    if ticker not in TICKERS or rows.empty:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return rows.sort_values("date"), meta


@app.get("/tickers")
def tickers() -> dict:
    frame, _ = _store()
    served = set(frame["ticker"])
    return {"tickers": [{"ticker": t, "name": name} for t, name in TICKERS.items() if t in served]}


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
                "realized_vol": None if math.isnan(row.realized_vol) else float(row.realized_vol),
            }
            for row in rows.itertuples()
        ],
    }
