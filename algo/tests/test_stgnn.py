"""The ST-GNN supervisor experiment: input builders, the network, the walk-forward and the gates.

Gate 3 (leakage) runs on synthetic data. Gates 1, 2 and 4 run on the committed
artifacts; gate 4 also needs the frozen price cache and is skipped without it.
"""
import numpy as np
import pandas as pd
import pytest

from tests.conftest import make_panel
from tsm.models import stgnn
from tsm.models.graph import correlation_adjacency_series

SKILLS = ["a", "b", "c", "d"]


def synthetic_frame(panel, start=120, seed=0):
    """A predictions.csv-like frame: one row per ticker and position from ``start`` on."""
    rng = np.random.default_rng(seed)
    rows = []
    days = len(next(iter(panel.values())))
    for ticker in panel:
        level = 0.2 * np.exp(np.cumsum(rng.normal(0, 0.05, days)))
        for position in range(start, days):
            row = {"date": panel[ticker].index[position], "ticker": ticker, "position": position}
            for k, skill in enumerate(SKILLS):
                row[f"pred_{skill}"] = level[position] * np.exp(rng.normal(0, 0.1 + 0.05 * k))
            row["realized_vol"] = level[position] * np.exp(rng.normal(0, 0.2))
            row["earnings_week"] = bool(rng.random() < 0.08)
            rows.append(row)
    frame = pd.DataFrame(rows)
    last = frame["position"] > days - 1 - stgnn.HORIZON_DAYS
    frame.loc[last, "realized_vol"] = np.nan  # the last 5 outcomes are not known yet
    return frame


@pytest.fixture
def setup():
    panel = make_panel(n_days=330)
    frame = synthetic_frame(panel)
    return panel, frame


def test_arrays_follow_positions(setup):
    _, frame = setup
    data = stgnn.frame_arrays(frame, SKILLS)
    assert data.preds.shape == (210, 3, 4)
    assert list(data.positions) == list(range(120, 330))
    row = frame[(frame["ticker"] == "BBB") & (frame["position"] == 150)].iloc[0]
    assert data.preds[30, 1, 2] == row["pred_c"]
    assert data.errors[30, 1, 2] == pytest.approx(np.log(row["realized_vol"] / row["pred_c"]))


def test_error_window_uses_known_outcomes_only(setup):
    _, frame = setup
    data = stgnn.frame_arrays(frame, SKILLS)
    seq = stgnn.error_windows(data.errors, np.array([40]), window=10)
    assert seq.shape == (1, 3, 10, 4)
    # Last step of the window is row 40 - 5: the newest outcome known at row 40.
    np.testing.assert_array_equal(seq[0, :, -1], data.errors[35])
    np.testing.assert_array_equal(seq[0, :, 0], data.errors[26])


def test_spread_is_centred(setup):
    _, frame = setup
    data = stgnn.frame_arrays(frame, SKILLS)
    np.testing.assert_allclose(stgnn.spread(data.preds).sum(axis=-1), 0.0, atol=1e-12)


def test_untrained_network_is_the_equal_weight_average(setup):
    _, frame = setup
    data = stgnn.frame_arrays(frame, SKILLS)
    weights = stgnn.untrained_weights(data, np.arange(30, 60), window=10, graph_layers=1)
    np.testing.assert_array_equal(weights, 0.25)
    combined = stgnn.combine(weights, data.preds[30:60])
    np.testing.assert_allclose(combined, data.preds[30:60].mean(axis=-1), rtol=0, atol=1e-12)


def test_walk_forward_learns_to_trust_the_better_skill():
    panel = make_panel(n_days=330)
    frame = synthetic_frame(panel)
    rng = np.random.default_rng(5)
    # Skill "a" becomes nearly exact; the others stay noisy.
    frame["pred_a"] = frame["realized_vol"].fillna(0.2) * np.exp(rng.normal(0, 0.02, len(frame)))
    data = stgnn.frame_arrays(frame, SKILLS)
    out = stgnn.walk_forward(data, None, start=100, end=200, window=10, graph_layers=0, seed=0, every=50, steps=150)
    assert out.weights.shape == (101, 3, 4)
    np.testing.assert_allclose(out.weights.sum(axis=-1), 1.0, atol=1e-12)
    assert out.weights[:, :, 0].mean() > 0.4


def test_walk_forward_is_reproducible(setup):
    _, frame = setup
    data = stgnn.frame_arrays(frame, SKILLS)
    kwargs = dict(start=100, end=160, window=10, graph_layers=1, seed=3, every=30, steps=20)
    adjacency = np.broadcast_to(np.eye(3), (len(data.positions), 3, 3))
    first = stgnn.walk_forward(data, adjacency, **kwargs).weights
    second = stgnn.walk_forward(data, adjacency, **kwargs).weights
    np.testing.assert_array_equal(first, second)


def corrupt_after(panel, frame, cutoff):
    """Every price after row ``cutoff``, every prediction after it and every outcome revealed after it."""
    rng = np.random.default_rng(99)
    panel = {t: f.copy() for t, f in panel.items()}
    for f in panel.values():
        f.iloc[cutoff + 1 :, :4] *= np.exp(rng.normal(0, 0.5, (len(f) - cutoff - 1, 1)))
    frame = frame.copy()
    later = frame["position"] > cutoff
    for skill in SKILLS:
        frame.loc[later, f"pred_{skill}"] *= np.exp(rng.normal(0, 0.5, later.sum()))
    revealed_later = frame["position"] > cutoff - stgnn.HORIZON_DAYS
    frame.loc[revealed_later, "realized_vol"] *= np.exp(rng.normal(0, 0.5, revealed_later.sum()))
    return panel, frame


@pytest.mark.parametrize("graph_layers", [0, 1])
def test_no_look_ahead(setup, graph_layers):
    """Gate 3: corrupting the future leaves the inputs and the weights up to the cutoff unchanged."""
    panel, frame = setup
    cutoff = 237  # a panel row between two refits
    bad_panel, bad_frame = corrupt_after(panel, frame, cutoff)
    results = []
    for p, f in [(panel, frame), (bad_panel, bad_frame)]:
        data = stgnn.frame_arrays(f, SKILLS)
        adjacency = correlation_adjacency_series(p, window=60)[data.positions]
        idx = np.arange(100, 200)
        inputs = stgnn.error_windows(data.errors, idx, window=10), stgnn.spread(data.preds)[idx], adjacency[idx]
        out = stgnn.walk_forward(data, adjacency, start=100, end=200, window=10,
                                 graph_layers=graph_layers, seed=0, every=40, steps=30)
        results.append((inputs, out.weights))
    known = cutoff - 120 - 100 + 1  # outputs for positions 220 .. cutoff
    (good_inputs, good_w), (bad_inputs, bad_w) = results
    for good, bad in zip(good_inputs, bad_inputs):
        np.testing.assert_array_equal(good[:known], bad[:known])
    np.testing.assert_array_equal(good_w[:known], bad_w[:known])
    assert not np.array_equal(good_w[known:], bad_w[known:])  # the corruption did reach later dates


def test_confidence_uses_known_outcomes_only():
    combined = np.full((20, 2), 0.2)
    realized = np.full((20, 2), 0.2)
    conf = stgnn.confidence(combined, realized, window=3)
    assert np.all(conf[:5] == 0.5)  # nothing known yet
    np.testing.assert_allclose(conf[5:], 1.0)
    realized[10] = 0.4
    conf2 = stgnn.confidence(combined, realized, window=3)
    np.testing.assert_array_equal(conf2[:15], conf[:15])
    assert (conf2[15] < 1.0).all()


# ---------------------------------------------------------------- the runner, on the committed artifacts

from tsm import stgnn as runner  # noqa: E402
from tsm.config import DATA_DIR  # noqa: E402


@pytest.fixture(scope="module")
def experiment():
    return runner.Experiment.load(with_panel=False)


def test_gate_1_reproduces_the_current_supervisor(experiment):
    assert runner.gate_supervisor(experiment) <= runner.GATE_TOLERANCE


def test_gate_2_untrained_network_is_the_saved_equal_weight(experiment):
    assert runner.gate_equal_weight(experiment) <= runner.GATE_TOLERANCE


@pytest.mark.skipif(not (DATA_DIR / "SPY.csv").exists(), reason="needs the frozen price cache in algo/data/")
def test_gate_4_panel_dates_match_positions():
    assert runner.gate_dates(runner.Experiment.load())


def test_periods_are_2019_and_from_test_start(experiment):
    start, end = experiment.rows("validation")
    assert experiment.data.dates[start] == pd.Timestamp("2019-01-02")
    assert experiment.data.dates[end].year == 2019 and experiment.data.dates[end + 1].year == 2020
    start, end = experiment.rows("test")
    assert experiment.data.dates[start] >= pd.Timestamp("2020-01-01") > experiment.data.dates[start - 1]
    assert end == len(experiment.data.positions) - 1


def test_reference_scores_match_the_report(experiment):
    refs = runner.reference_scores(experiment)
    assert refs.loc["supervisor", "QLIKE"] == pytest.approx(0.4263, abs=5e-5)
    assert refs.loc["equal_weight", "QLIKE_2019"] == pytest.approx(0.4109, abs=5e-5)


def references(supervisor=0.4263, equal=0.4300, best=0.4275):
    return pd.DataFrame({"QLIKE": {"supervisor": supervisor, "equal_weight": equal, "a": best, "b": 0.5}})


def test_decision_needs_every_bar():
    d = runner.decide({0: 0.4200, 1: 0.4210, 2: 0.4220}, references(), ["a", "b"])
    assert d["go"] and d["settled"]
    d = runner.decide({0: 0.4200, 1: 0.4210, 2: 0.4300}, references(), ["a", "b"])
    assert not d["go"]  # one seed not below equal weight, though the mean beats every bar
    d = runner.decide({0: 0.4262, 1: 0.4264, 2: 0.4258}, references(), ["a", "b"])
    assert d["go"] and not d["settled"]  # it clears the bar, by less than the seed spread


def test_protected_files_are_hashed():
    hashes = runner.file_hashes()
    assert any(path.endswith("predictions.csv") for path in hashes)
    assert any(path.endswith("supervisor.py") for path in hashes)
