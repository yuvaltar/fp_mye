"""The experiment runner's cheap guards.

A walk-forward costs minutes, so anything that can be checked before it starts
has to be checked before it starts. These tests never run a model.
"""
import os

import numpy as np
import pandas as pd
import pytest

from tsm import data, experiment
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

    monkeypatch.setattr(experiment, "load_panel", fail)
    monkeypatch.setattr(experiment, "load_committee", fail)
    monkeypatch.setattr(experiment, "run_candidates", fail)
    with pytest.raises(ValueError, match="no DESCRIPTIONS entry for undescribed"):
        experiment.main(["undescribed"])


def test_main_rejects_an_unknown_candidate_name(monkeypatch):
    monkeypatch.setattr(experiment, "load_panel", lambda *a, **k: pytest.fail("should not run"))
    with pytest.raises(ValueError, match="unknown candidate"):
        experiment.main(["not_a_model"])


class ReachedTheWalkForward(Exception):
    """Raised by the stub walk-forward, so a test stops main there without running a model."""


@pytest.fixture
def old_cache(tmp_path, monkeypatch):
    """A two-ticker price cache dated weeks ago, which the normal loader would download again.

    main is stubbed around the panel: the committee read returns nothing and the
    walk-forward records the panel it was handed, then stops.
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

    monkeypatch.setattr(data, "TICKERS", tickers)
    monkeypatch.setattr(data, "_cache_path", lambda ticker, data_dir: tmp_path / f"{ticker}.csv")
    monkeypatch.setattr(data, "_download", lambda *a, **k: pytest.fail("tsm.experiment downloaded prices"))
    monkeypatch.setattr(experiment, "load_committee", lambda: (pd.DataFrame(), ["short_term"]))
    seen = {}

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
    pd.testing.assert_frame_equal(seen["panel"]["AAA"], expected)


def test_main_stops_on_a_missing_cache_file_before_the_walk_forward(old_cache):
    cache_dir, seen = old_cache
    (cache_dir / "BBB.csv").unlink()
    with pytest.raises(FileNotFoundError, match="no cached prices for BBB"):
        experiment.main(["itransformer_mae"])
    assert "panel" not in seen
