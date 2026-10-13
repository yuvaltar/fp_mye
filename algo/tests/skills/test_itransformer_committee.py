"""The committee's itransformer: path_feats at seeds 0, 1 and 2, averaged."""
import pytest

from tsm.data import truncate_panel
from tsm.models.itransformer import CANDIDATES, ITransformerSkill
from tsm.skills.itransformer import SEEDS, ITransformerCommitteeSkill

SMALL = dict(input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=5)


def test_it_is_path_feats_at_three_seeds():
    skill = ITransformerCommitteeSkill(**SMALL)
    assert [m.seed for m in skill.members] == list(SEEDS) == [0, 1, 2]
    settings = {k: v for k, v in CANDIDATES["itransformer_path_feats"].items() if k != "name"}
    for member in skill.members:
        assert {k: getattr(member, k) for k in settings} == settings


def test_the_prediction_is_the_mean_of_the_three_seeds(panel):
    known = truncate_panel(panel, 300)
    skill = ITransformerCommitteeSkill(**SMALL)
    skill.fit(known)
    alone = []
    settings = {k: v for k, v in CANDIDATES["itransformer_path_feats"].items() if k != "name"}
    for seed in SEEDS:
        member = ITransformerSkill(seed=seed, **{**settings, **SMALL})
        member.fit(known)
        alone.append(member.predict(known))
    expected = {t: sum(p[t] for p in alone) / len(alone) for t in panel}
    assert skill.predict(known) == pytest.approx(expected, rel=1e-12)
