"""Checks every registered skill has to pass."""
import math

import pytest

from tsm.data import truncate_panel
from tsm.models.itransformer import ITransformerSkill
from tsm.skills.multivariate import MultivariateSkill
from tsm.skills.regime import RegimeSkill
from tsm.skills.short_term import ShortTermSkill
from tsm.skills.weak_signals import WeakSignalsSkill
from tsm.supervisor import build_skills

from tests.conftest import corrupt_after

SKILLS = {
    "short_term": ShortTermSkill,
    "regime": RegimeSkill,
    "weak_signals": WeakSignalsSkill,
    # A tiny network keeps the test fast; the architecture is the same.
    "multivariate": lambda: MultivariateSkill(input_size=20, hidden_size=8, max_steps=5),
}

# Experiment skills: they must pass every check below, but they are not in the
# committee, so the registry test above stays on SKILLS alone.
CANDIDATES = {
    "itransformer_mae": lambda: ITransformerSkill(
        loss="mae", input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5
    ),
    "itransformer_qlike": lambda: ITransformerSkill(
        loss="qlike", input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5
    ),
    "itransformer_mae_path": lambda: ITransformerSkill(
        loss="mae", path=True, input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5
    ),
}
ALL = SKILLS | CANDIDATES
AS_OF = 300


def test_registry_matches_the_tested_skills():
    registered = build_skills()
    assert [s.name for s in registered] == list(SKILLS)
    assert all(s.horizon in {"short", "medium", "long"} for s in registered)


@pytest.mark.parametrize("name", ALL)
def test_predicts_a_positive_vol_per_ticker(name, panel):
    skill = ALL[name]()
    known = truncate_panel(panel, AS_OF)
    skill.fit(known)
    predicted = skill.predict(known)
    assert set(predicted) == set(panel)
    assert all(math.isfinite(v) and 0 < v < 5 for v in predicted.values())


@pytest.mark.parametrize("name", ALL)
def test_deterministic(name, panel):
    known = truncate_panel(panel, AS_OF)
    runs = []
    for _ in range(2):
        skill = ALL[name]()
        skill.fit(known)
        runs.append(skill.predict(known))
    assert runs[0] == pytest.approx(runs[1])


@pytest.mark.parametrize("name", ALL)
def test_no_future_leakage(name, panel):
    """Garbage written after the as-of date must not change the prediction."""
    predictions = []
    for source in (panel, corrupt_after(panel, AS_OF)):
        known = truncate_panel(source, AS_OF)
        skill = ALL[name]()
        skill.fit(known)
        predictions.append(skill.predict(known))
    assert predictions[0] == pytest.approx(predictions[1])


@pytest.mark.parametrize("name", ALL)
def test_predict_reads_new_data_without_refit(name, panel):
    """Between two fits, predict must still react to the days that arrived since."""
    skill = ALL[name]()
    skill.fit(truncate_panel(panel, AS_OF))
    before = skill.predict(truncate_panel(panel, AS_OF))
    after = skill.predict(truncate_panel(panel, AS_OF + 10))
    assert before != pytest.approx(after)
