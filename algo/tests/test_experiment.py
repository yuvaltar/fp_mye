"""The experiment runner's cheap guards.

A walk-forward costs minutes, so anything that can be checked before it starts
has to be checked before it starts. These tests never run a model.
"""
import json
import os

import numpy as np
import pandas as pd
import pytest

from tsm import data, experiment
from tsm.config import VIX_TICKER
from tsm.models.itransformer import CANDIDATES


def test_every_registered_candidate_has_a_description():
    """The regression this guard exists for: a candidate with no description wrote blank cells."""
    missing = [name for name in CANDIDATES if name not in experiment.DESCRIPTIONS]
    assert missing == [], f"add a DESCRIPTIONS entry for {missing}"


def test_every_seeded_committee_row_has_a_description():
    missing = [name for name in experiment.SEED_MODELS if name not in experiment.DESCRIPTIONS]
    assert missing == []


def test_check_descriptions_accepts_the_registered_candidates():
    experiment.check_descriptions(list(CANDIDATES))


def test_check_descriptions_names_what_is_missing():
    with pytest.raises(ValueError, match="no DESCRIPTIONS entry for brand_new_model"):
        experiment.check_descriptions(["brand_new_model"])


def test_main_refuses_before_touching_the_panel(monkeypatch):
    """The guard must fire before the walk-forward, not after it."""
    monkeypatch.setitem(CANDIDATES, "undescribed", {"loss": "mae"})

    def fail(*args, **kwargs):
        raise AssertionError("main reached the data layer before checking descriptions")

    monkeypatch.setattr(experiment, "load_frozen_panel", fail)
    monkeypatch.setattr(experiment, "load_committee", fail)
    monkeypatch.setattr(experiment, "run_candidates", fail)
    with pytest.raises(ValueError, match="no DESCRIPTIONS entry for undescribed"):
        experiment.main(["undescribed"])


def test_main_rejects_an_unknown_candidate_name(monkeypatch):
    monkeypatch.setattr(experiment, "load_frozen_panel", lambda *a, **k: pytest.fail("should not run"))
    with pytest.raises(ValueError, match="unknown candidate"):
        experiment.main(["not_a_model"])


class ReachedTheWalkForward(Exception):
    """Raised by the stub walk-forward, so a test stops main there without running a model."""


@pytest.fixture
def old_cache(tmp_path, monkeypatch):
    """A two-ticker price cache dated weeks ago, which the normal loader would download again.

    Its meta.json says the artifacts were built on prices ending on the cache's
    last day. main is stubbed around the panel: the committee read records that it
    happened and returns nothing, and the walk-forward records the panel it was
    handed, then stops.
    """
    tickers = {"AAA": "Company A", "BBB": "Company B"}
    dates = pd.bdate_range("2024-01-02", periods=30, name="date")
    old = pd.Timestamp("2024-03-01").timestamp()
    for i, ticker in enumerate(tickers):
        close = np.linspace(10, 12, len(dates)) + i
        frame = pd.DataFrame(
            {"open": close, "high": close + 0.5, "low": close - 0.5, "close": close, "volume": 1000.0},
            index=dates,
        )
        frame.to_csv(tmp_path / f"{ticker}.csv")
        os.utime(tmp_path / f"{ticker}.csv", (old, old))

    vix = pd.DataFrame(
        {"open": 15.0, "high": 16.0, "low": 14.0, "close": np.linspace(14, 20, len(dates)), "volume": 0.0},
        index=dates,
    )
    vix.to_csv(tmp_path / f"{VIX_TICKER}.csv")
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps({"last_date": str(dates[-1].date())}))

    monkeypatch.setattr(experiment, "TICKERS", tickers)
    monkeypatch.setattr(experiment, "META_FILE", meta)
    monkeypatch.setattr(data, "_cache_path", lambda ticker, data_dir: tmp_path / f"{ticker}.csv")
    monkeypatch.setattr(data, "_download", lambda *a, **k: pytest.fail("tsm.experiment downloaded prices"))
    seen = {}

    def committee():
        seen["committee"] = True
        return pd.DataFrame(), ["short_term"]

    monkeypatch.setattr(experiment, "load_committee", committee)

    def stop(panel, skills, verbose=True):
        seen["panel"] = panel
        raise ReachedTheWalkForward

    monkeypatch.setattr(experiment, "run_candidates", stop)
    return tmp_path, seen


def test_main_reads_the_price_cache_and_never_downloads(old_cache):
    """The committee was scored on the cached prices, so candidates must see the same ones."""
    cache_dir, seen = old_cache
    with pytest.raises(ReachedTheWalkForward):
        experiment.main(["itransformer_mae"])
    assert list(seen["panel"]) == ["AAA", "BBB"]
    expected = pd.read_csv(cache_dir / "AAA.csv", index_col="date", parse_dates=["date"])
    # Prices exactly as cached; the added vix column is checked in its own test.
    pd.testing.assert_frame_equal(seen["panel"]["AAA"].drop(columns="vix"), expected)


def test_main_stops_on_a_missing_cache_file_before_the_walk_forward(old_cache):
    cache_dir, seen = old_cache
    (cache_dir / "BBB.csv").unlink()
    with pytest.raises(FileNotFoundError, match="no cached prices for BBB"):
        experiment.main(["itransformer_mae"])
    assert "panel" not in seen


def test_main_refuses_a_cache_that_does_not_end_on_the_artifacts_last_date(old_cache):
    """A cache refreshed after the backtest holds other prices than the ones the committee saw."""
    cache_dir, seen = old_cache
    meta = cache_dir / "meta.json"
    built_on = pd.Timestamp(json.loads(meta.read_text())["last_date"])
    meta.write_text(json.dumps({"last_date": str((built_on - pd.offsets.BDay(1)).date())}))
    with pytest.raises(ValueError, match="does not match the committed artifacts"):
        experiment.main(["itransformer_mae"])
    assert "committee" not in seen and "panel" not in seen


def test_main_refuses_when_a_single_ticker_was_downloaded_again(old_cache):
    """Aligning the panel would hide this one, so the check runs per ticker."""
    cache_dir, seen = old_cache
    path = cache_dir / "BBB.csv"
    frame = pd.read_csv(path, index_col="date", parse_dates=["date"])
    extra = frame.iloc[[-1]].set_axis([frame.index[-1] + pd.offsets.BDay(1)]).rename_axis("date")
    pd.concat([frame, extra]).to_csv(path)
    with pytest.raises(ValueError, match=r"1 ticker\(s\) \(BBB\)"):
        experiment.main(["itransformer_mae"])
    assert "committee" not in seen and "panel" not in seen


def test_migrate_table_adds_the_new_columns_and_keeps_every_value(tmp_path, monkeypatch):
    path = tmp_path / "experiments.md"
    old = [
        "# Experiments", "", "old text", "",
        experiment.OLD_TABLE_HEADER,
        "| --- | --- | --- | ---: | ---: | ---: | ---: |",
        "| 2026-10-08 | `regime` | GARCH(1,1) on daily returns | 0.5342 | +2.2% | 1.065 | — |",
        "| 2026-10-08 | `itransformer_mae` | Own PyTorch iTransformer, MAE | 0.5244 | +4.0% | 1.319 | 451s |",
    ]
    path.write_text("\n".join(old) + "\n", encoding="utf-8")
    monkeypatch.setattr(experiment, "EXPERIMENTS_FILE", path)

    assert experiment.migrate_table() is True
    lines = path.read_text(encoding="utf-8").splitlines()
    header = next(line for line in lines if line.startswith("| Date"))
    assert header == "| Date | Experiment | Description | QLIKE | vs HAR-RV | QLIKE 2019 | Mean factor | Gate | Runtime |"
    rows = [line for line in lines if line.startswith("| 2026")]
    assert rows == [
        "| 2026-10-08 | `regime` | GARCH(1,1) on daily returns | 0.5342 | +2.2% | — | 1.065 | — | — |",
        "| 2026-10-08 | `itransformer_mae` | Own PyTorch iTransformer, MAE | 0.5244 | +4.0% | — | 1.319 | — | 451s |",
    ]
    assert experiment.migrate_table() is False  # already current: nothing to do


def test_validation_rows_are_2019_with_a_known_outcome():
    dates = pd.to_datetime(["2018-12-31", "2019-01-02", "2019-12-31", "2020-01-02", "2019-06-03"])
    frame = pd.DataFrame(
        {"date": dates, "realized_vol": [0.2, 0.2, 0.2, 0.2, np.nan], "pred_x": 0.3}
    )
    picked = experiment.validation_rows(frame)
    assert picked["date"].dt.strftime("%Y-%m-%d").tolist() == ["2019-01-02", "2019-12-31"]


def test_the_frozen_panel_carries_the_vix_close_in_every_frame(old_cache):
    cache_dir, seen = old_cache
    with pytest.raises(ReachedTheWalkForward):
        experiment.main(["itransformer_mae"])
    vix = pd.read_csv(cache_dir / f"{VIX_TICKER}.csv", index_col="date", parse_dates=["date"])["close"]
    for frame in seen["panel"].values():
        np.testing.assert_array_equal(frame["vix"].to_numpy(), vix.to_numpy())


def test_a_stock_day_without_vix_takes_the_day_before(old_cache):
    cache_dir, seen = old_cache
    path = cache_dir / f"{VIX_TICKER}.csv"
    vix = pd.read_csv(path, index_col="date", parse_dates=["date"])
    vix.drop(vix.index[10]).to_csv(path)
    with pytest.raises(ReachedTheWalkForward):
        experiment.main(["itransformer_mae"])
    column = seen["panel"]["AAA"]["vix"]
    assert len(column) == len(vix)  # the stocks keep every one of their days
    assert column.iloc[10] == vix["close"].iloc[9]


def test_main_refuses_a_vix_cache_that_does_not_end_on_last_date(old_cache):
    cache_dir, seen = old_cache
    path = cache_dir / f"{VIX_TICKER}.csv"
    pd.read_csv(path, index_col="date", parse_dates=["date"]).iloc[:-1].to_csv(path)
    with pytest.raises(ValueError, match=r"\^VIX"):
        experiment.main(["itransformer_mae"])
    assert "committee" not in seen and "panel" not in seen


def test_main_stops_when_the_vix_was_never_frozen(old_cache):
    cache_dir, seen = old_cache
    (cache_dir / f"{VIX_TICKER}.csv").unlink()
    with pytest.raises(FileNotFoundError, match=r"\^VIX"):
        experiment.main(["itransformer_mae"])
    assert "panel" not in seen
