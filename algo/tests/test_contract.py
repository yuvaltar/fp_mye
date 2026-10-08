"""Checks that the mock files in /contracts conform to the API contract."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SCHEMA = json.loads((CONTRACTS / "prediction.schema.json").read_text())


def load(name):
    return json.loads((CONTRACTS / name).read_text())


def validator(definition):
    schema = {**SCHEMA, "$ref": f"#/$defs/{definition}"}
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_schema_is_valid():
    Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize("prediction", load("mock_prediction.json"), ids=lambda p: p["ticker"])
def test_mock_prediction(prediction):
    validator("Prediction").validate(prediction)
    assert sum(s["weight"] for s in prediction["skills"]) == pytest.approx(1.0)


def test_mock_prediction_covers_expected_tickers():
    assert [p["ticker"] for p in load("mock_prediction.json")] == ["AAPL", "TEVA", "NVDA"]


def test_mock_tickers():
    validator("TickersResponse").validate(load("mock_tickers.json"))


@pytest.mark.parametrize("history", load("mock_history.json"), ids=lambda h: h["ticker"])
def test_mock_history(history):
    validator("HistoryResponse").validate(history)


def test_schema_rejects_bad_prediction():
    bad = {**load("mock_prediction.json")[0], "horizon_days": 10}
    assert not validator("Prediction").is_valid(bad)
