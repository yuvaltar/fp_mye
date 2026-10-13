"""The report generator is only imported inside ``backtest.main()``, so nothing else
exercises it: a syntax error or a bad format string there survives the whole suite and
only shows up at the end of a long run. These tests render a real report from a small
synthetic frame instead, which is fast because no skill is fitted.
"""
import numpy as np
import pandas as pd
import pytest

from tsm.backtest import CALIBRATION_WINDOW
from tsm.report import write_report

SKILLS = [
    {"name": "short_term", "horizon": "short"},
    {"name": "regime", "horizon": "long"},
]
SKILL_NAMES = [s["name"] for s in SKILLS]
TICKERS = ["AAA", "BBB"]
TEST_START = "2020-01-01"


@pytest.fixture
def frame():
    """One row per (date, ticker) with every column write_report reads."""
    rng = np.random.default_rng(0)
    dates = pd.bdate_range("2019-10-01", periods=80)
    rows = []
    for position, date in enumerate(dates):
        for ticker in TICKERS:
            realized = float(0.2 + 0.05 * rng.normal())
            preds = {name: abs(realized + 0.02 * rng.normal()) for name in SKILL_NAMES}
            row = {"date": date, "ticker": ticker, "position": position, "realized_vol": realized}
            for name, value in preds.items():
                row[f"raw_pred_{name}"] = value
                row[f"c_{name}"] = 1.1
                row[f"pred_{name}"] = value * 1.1
                row[f"w_{name}"] = 0.5
            row["naive"] = abs(realized + 0.03 * rng.normal())
            row["equal_weight"] = float(np.mean([row[f"pred_{n}"] for n in SKILL_NAMES]))
            row["baseline"] = row["pred_short_term"]
            row["supervisor"] = row["equal_weight"]
            row["confidence"] = 0.6
            rows.append(row)
    frame = pd.DataFrame(rows)
    # The last horizon of dates has no known outcome yet, as in a real run.
    frame.loc[frame["position"] >= len(dates) - 5, "realized_vol"] = np.nan
    return frame


@pytest.fixture
def meta():
    return {
        "model_version": "0.0.0-test",
        "skills": SKILLS,
        "supervisor": {"window": 60, "temperature": 0.25},
        "test_start": TEST_START,
        "last_date": "2020-01-21",
        "calibration_window": CALIBRATION_WINDOW,
    }


def test_write_report_renders_every_section(frame, meta, tmp_path):
    table = write_report(frame, meta, docs_dir=tmp_path)
    text = (tmp_path / "backtest.md").read_text(encoding="utf-8")
    for heading in (
        "# Backtest report",
        "## Summary",
        "## Setup",
        "## Metrics vs baselines",
        "## Before vs after calibration",
        "## Average weight per skill",
        "## Charts",
        "## Caveats",
    ):
        assert heading in text
    # Every model of the metrics table reached the file, and no placeholder was left behind.
    for model in ("Supervisor (the market)", "HAR-RV baseline", "Naive", "Equal-weight average"):
        assert model in text
    assert "{" not in text and "}" not in text
    assert set(table.index) == {"supervisor", "baseline", "regime", "naive", "equal_weight"}


def test_report_is_written_as_utf8(frame, meta, tmp_path):
    """The em-dash placeholders must survive: Windows defaults to a codepage that mangles them."""
    write_report(frame, meta, docs_dir=tmp_path)
    raw = (tmp_path / "backtest.md").read_bytes()
    assert "—".encode("utf-8") in raw
    text = raw.decode("utf-8")  # fails outright if another encoding was used
    assert "�" not in text


def test_calibration_section_reports_the_factor_and_both_losses(frame, meta, tmp_path):
    write_report(frame, meta, docs_dir=tmp_path)
    text = (tmp_path / "backtest.md").read_text(encoding="utf-8")
    section = text[text.index("## Before vs after calibration"):text.index("## Average weight per skill")]
    assert "| Model | Mean factor | Mean raw bias | QLIKE before | QLIKE after | QLIKE change |" in section
    for name in SKILL_NAMES:
        assert f"| Skill `{name}` |" in section
    # The synthetic factor is a constant 1.1, so it must be reported as such.
    assert section.count("| 1.100 |") == len(SKILL_NAMES)
    assert str(CALIBRATION_WINDOW) in section


def test_write_report_creates_assets_and_charts(frame, meta, tmp_path):
    write_report(frame, meta, docs_dir=tmp_path)
    assets = tmp_path / "backtest_assets"
    for name in (
        "predicted_vs_realized.png",
        "weights_over_time.png",
        "qlike_per_model.png",
        "results.csv",
        "weights.csv",
    ):
        assert (assets / name).exists() and (assets / name).stat().st_size > 0


def test_report_scores_only_dates_with_a_known_outcome(frame, meta, tmp_path):
    write_report(frame, meta, docs_dir=tmp_path)
    text = (tmp_path / "backtest.md").read_text(encoding="utf-8")
    scored = frame[(frame["date"] >= pd.Timestamp(TEST_START)) & frame["realized_vol"].notna()]
    assert f"{len(scored)} scored predictions" in text
