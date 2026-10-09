"""The experiment runner's cheap guards.

A walk-forward costs minutes, so anything that can be checked before it starts
has to be checked before it starts. These tests never run a model.
"""
import pytest

from tsm import experiment
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
