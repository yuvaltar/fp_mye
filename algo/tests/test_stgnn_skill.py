"""The ST-GNN predictor candidate: same checks as every skill in tests/skills/test_skills.py."""
import math

import numpy as np
import pytest

from tests.conftest import corrupt_after, make_panel
from tsm.backtest import run_skills
from tsm.data import truncate_panel
from tsm.models.stgnn_skill import CANDIDATES, STGNNSkill, build_candidate

AS_OF = 300
SMALL = dict(max_steps=20, hidden=8, input_size=20)


@pytest.fixture(scope="module")
def panel():
    return make_panel(n_days=420)


@pytest.mark.parametrize("source", ["none", "corr", "shuffled"])
def test_predicts_a_positive_vol_per_ticker(source, panel):
    skill = STGNNSkill(graph_source=source, **SMALL)
    known = truncate_panel(panel, AS_OF)
    skill.fit(known)
    predicted = skill.predict(known)
    assert set(predicted) == set(panel)
    assert all(math.isfinite(v) and 0 < v < 5 for v in predicted.values())


@pytest.mark.parametrize("source", ["none", "corr"])
def test_deterministic(source, panel):
    known = truncate_panel(panel, AS_OF)
    runs = []
    for _ in range(2):
        skill = STGNNSkill(graph_source=source, **SMALL)
        skill.fit(known)
        runs.append(skill.predict(known))
    assert runs[0] == runs[1]


@pytest.mark.parametrize("source", ["none", "corr", "shuffled"])
def test_no_future_leakage(source, panel):
    predictions = []
    for data in (panel, corrupt_after(panel, AS_OF)):
        known = truncate_panel(data, AS_OF)
        skill = STGNNSkill(graph_source=source, **SMALL)
        skill.fit(known)
        predictions.append(skill.predict(known))
    assert predictions[0] == predictions[1]


def test_no_future_leakage_in_the_walk_forward(panel):
    """Through run_skills, with refits: every prediction up to the cutoff is unchanged."""
    outs = []
    for data in (panel, corrupt_after(panel, AS_OF)):
        skill = STGNNSkill(graph_source="corr", **{**SMALL, "max_steps": 5})
        skill.refit_every_days = 40
        outs.append(run_skills(data, [skill], start=str(data["AAA"].index[250].date())))
    good, bad = outs
    known = good["position"] <= AS_OF
    np.testing.assert_array_equal(good.loc[known, "pred_stgnn_skill_corr"], bad.loc[known, "pred_stgnn_skill_corr"])
    assert not np.array_equal(good.loc[~known, "pred_stgnn_skill_corr"], bad.loc[~known, "pred_stgnn_skill_corr"])


def test_predict_reads_new_data_without_refit(panel):
    skill = STGNNSkill(graph_source="corr", **SMALL)
    skill.fit(truncate_panel(panel, AS_OF))
    before = skill.predict(truncate_panel(panel, AS_OF))
    after = skill.predict(truncate_panel(panel, AS_OF + 10))
    assert before != pytest.approx(after)


def test_graph_starts_switched_off(panel):
    """With the gate at 0 before training, the graph and no-graph models agree exactly."""
    known = truncate_panel(panel, AS_OF)
    outs = []
    for source in ("none", "corr"):
        skill = STGNNSkill(graph_source=source, **{**SMALL, "max_steps": 0})
        skill.fit(known)
        outs.append(skill.predict(known))
    assert outs[0] == outs[1]


def test_candidates_by_name():
    assert set(CANDIDATES) == {"stgnn_skill_none", "stgnn_skill_corr", "stgnn_skill_shuffled"}
    skill = build_candidate("stgnn_skill_shuffled", seed=2)
    assert skill.name == "stgnn_skill_shuffled" and skill.seed == 2 and skill.graph


# ---------------------------------------------------------------- the committee runner, on the committed artifacts

import pandas as pd  # noqa: E402

from tsm import stgnn_skill as runner  # noqa: E402


@pytest.fixture(scope="module")
def committed():
    return runner.load_frame()


def test_gates_rebuild_the_saved_committee(committed):
    frame, skills, meta = committed
    result, four = runner.gates(frame, skills, meta)
    assert result["supervisor settings reproduced"]
    ref = runner.qlikes(four, ["supervisor", "equal_weight"])
    assert ref.loc["supervisor", "QLIKE"] == pytest.approx(0.4263, abs=5e-5)
    assert ref.loc["equal_weight", "QLIKE"] == pytest.approx(0.4300, abs=5e-5)


def test_a_copy_of_a_member_changes_nothing_in_equal_weight_terms(committed):
    """A fifth member identical to the equal-weight mix leaves the equal-weight average unchanged."""
    frame, skills, _ = committed
    base = {s: frame[f"raw_pred_{s}"] for s in skills}
    four, _ = runner.committee(frame, base)
    five, _ = runner.committee(frame, {**base, "copy": frame["raw_pred_weak_signals"]})
    expected = (4 * four["equal_weight"] + five["pred_copy"]) / 5
    np.testing.assert_allclose(five["equal_weight"], expected, rtol=0, atol=1e-12)


def test_decision_needs_both_bars():
    four = pd.Series({"supervisor": 0.4263, "equal_weight": 0.4300})
    d = runner.decide(pd.Series({"supervisor": 0.4250, "equal_weight": 0.4280}), four, [0.4248, 0.4251, 0.4252])
    assert d["go"] and d["settled"]
    d = runner.decide(pd.Series({"supervisor": 0.4250, "equal_weight": 0.4310}), four, [0.4250, 0.4250, 0.4250])
    assert not d["go"]
    d = runner.decide(pd.Series({"supervisor": 0.4262, "equal_weight": 0.4290}), four, [0.4255, 0.4262, 0.4270])
    assert d["go"] and not d["settled"]
