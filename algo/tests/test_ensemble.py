"""python -m tsm.ensemble: combinations of saved predictions, chosen on 2019 only."""
import numpy as np
import pandas as pd
import pytest

from tsm import ensemble, experiment
from tsm.backtest import calibrate

COMMITTEE = ["short_term", "regime", "weak_signals", "multivariate"]
SEEDS = [0, 1, 2]


def saved_committee(seed: int = 0) -> pd.DataFrame:
    """What load_committee returns: raw predictions around a known realized volatility."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2018-01-02", "2021-06-30")
    rows = []
    for t, ticker in enumerate(["AAA", "BBB"]):
        vol = np.exp(np.cumsum(rng.normal(0, 0.05, len(dates)))) * (0.2 + 0.1 * t)
        frame = pd.DataFrame({"date": dates, "ticker": ticker, "position": np.arange(len(dates))})
        frame["realized_vol"] = vol * np.exp(rng.normal(0, 0.3, len(dates)))
        frame.loc[frame.index[-5:], "realized_vol"] = np.nan  # outcome not known yet
        for i, name in enumerate(COMMITTEE):
            frame[f"pred_{name}"] = vol * (0.8 + 0.05 * i) * np.exp(rng.normal(0, 0.2, len(dates)))
        rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def write_component(directory, committee: pd.DataFrame, seeds=SEEDS) -> None:
    rng = np.random.default_rng(42)
    for seed in seeds:
        saved = committee[["date", "ticker"]].copy()
        saved["prediction"] = committee["pred_weak_signals"] * np.exp(rng.normal(0, 0.15, len(committee)))
        saved.to_csv(directory / f"{ensemble.component_name(seed)}.csv", index=False)


@pytest.fixture
def frame(tmp_path):
    committee = saved_committee()
    write_component(tmp_path, committee)
    return committee.merge(ensemble.load_component(SEEDS, tmp_path), on=["date", "ticker"])


def test_combinations_are_means_of_calibrated_predictions(frame):
    built = ensemble.build(frame, COMMITTEE, SEEDS)
    calibrated = calibrate(frame, COMMITTEE + [ensemble.component_name(s) for s in SEEDS])
    pf = calibrated["pred_itransformer_path_feats_seed1"]
    np.testing.assert_allclose(built["pred_pair_equal_seed1"], 0.5 * calibrated["pred_weak_signals"] + 0.5 * pf)
    np.testing.assert_allclose(built["pred_pair_w0.0_seed1"], calibrated["pred_weak_signals"])
    np.testing.assert_allclose(built["pred_pair_w1.0_seed1"], pf)
    members = calibrated[["pred_short_term", "pred_regime", "pred_weak_signals"]].sum(axis=1) + pf
    np.testing.assert_allclose(built["pred_committee_v2_seed1"], members / 4)


def test_committee_v2_drops_multivariate(frame):
    before = ensemble.build(frame, COMMITTEE, SEEDS)["pred_committee_v2_seed0"]
    changed = frame.assign(pred_multivariate=frame["pred_multivariate"] * 3)
    np.testing.assert_array_equal(ensemble.build(changed, COMMITTEE, SEEDS)["pred_committee_v2_seed0"], before)
    changed = frame.assign(pred_regime=frame["pred_regime"] * 3)
    assert not np.allclose(ensemble.build(changed, COMMITTEE, SEEDS)["pred_committee_v2_seed0"], before)


def test_the_weight_is_chosen_on_2019_only():
    """2019 favours w=0.3, the test period w=0.9: the choice must follow 2019."""
    rows = {}
    for w in ensemble.WEIGHTS:
        for s in SEEDS:
            rows[f"pair_w{w:.1f}_seed{s}"] = {"QLIKE_2019": 0.5 + abs(w - 0.3), "QLIKE": 0.5 + abs(w - 0.9)}
    w, scan = ensemble.choose_weight(pd.DataFrame(rows).T, SEEDS)
    assert w == pytest.approx(0.3)
    assert list(scan.index) == list(ensemble.WEIGHTS)


def test_a_tie_goes_to_the_smaller_weight():
    rows = {f"pair_w{w:.1f}_seed{s}": {"QLIKE_2019": 0.5, "QLIKE": 0.5} for w in ensemble.WEIGHTS for s in SEEDS}
    assert ensemble.choose_weight(pd.DataFrame(rows).T, SEEDS)[0] == 0.0


def test_a_missing_seed_file_names_the_command_to_run(tmp_path):
    with pytest.raises(FileNotFoundError, match="python -m tsm.experiment itransformer_path_feats --seeds 0 1 2"):
        ensemble.load_component(SEEDS, tmp_path)


def test_main_appends_one_row_per_seed_and_a_summary_per_combination(tmp_path, monkeypatch):
    committee = saved_committee()
    write_component(tmp_path, committee)
    monkeypatch.setattr(ensemble, "load_committee", lambda: (committee, COMMITTEE))
    monkeypatch.setattr(experiment, "EXPERIMENTS_DIR", tmp_path)
    monkeypatch.setattr(experiment, "EXPERIMENTS_FILE", tmp_path / "experiments.md")

    ensemble.main([])
    text = (tmp_path / "experiments.md").read_text(encoding="utf-8")
    for name in ensemble.COMBINATIONS:
        assert sum(f"| `{name}` (seed {s}) |" in text for s in SEEDS) == 3
        assert f"**`{name}` mean of 3 seeds**" in text
    assert "w chosen on mean 2019 QLIKE" in text
    assert "pair_w" not in text  # the scan is printed, never written as rows


def test_main_refuses_runs_that_do_not_cover_the_committee(tmp_path, monkeypatch):
    committee = saved_committee()
    write_component(tmp_path, committee.iloc[:-10])
    monkeypatch.setattr(ensemble, "load_committee", lambda: (committee, COMMITTEE))
    monkeypatch.setattr(experiment, "EXPERIMENTS_DIR", tmp_path)
    with pytest.raises(ValueError, match="cover"):
        ensemble.main([])
