"""The graph options of our iTransformer: they start as the plain model and only the gates decide."""
import numpy as np
import pytest
import torch

from tsm.data import truncate_panel
from tsm.models.itransformer import (
    GATE_LEARNING_RATE,
    ITransformer,
    ITransformerSkill,
    _shuffled,
    summarize_gates,
)

STOCKS, CHANNELS, DAYS = 6, 4, 20


def build(graph=None, seed=0, dropout=0.1):
    torch.manual_seed(seed)
    return ITransformer(
        input_size=DAYS, hidden_size=8, n_heads=2, d_ff=16, dropout=dropout,
        n_outputs=5, n_channels=CHANNELS, graph=graph,
    )


def inputs(seed=1):
    generator = torch.Generator().manual_seed(seed)
    windows = torch.randn(3, STOCKS, CHANNELS, DAYS, generator=generator)
    # A sparse map: each stock linked to itself and the next one, rows summing to 1.
    adjacency = torch.eye(STOCKS) + torch.roll(torch.eye(STOCKS), 1, dims=1)
    adjacency = (adjacency + adjacency.T).clamp(max=1)
    adjacency = (adjacency / adjacency.sum(dim=1, keepdim=True)).expand(3, STOCKS, STOCKS)
    return windows, adjacency


@pytest.mark.parametrize("graph", ["gnn", "bias"])
def test_starts_as_the_plain_model(graph):
    """Same seed, gates at 0: same weights and same output as path_feats."""
    plain, graphed = build(), build(graph)
    for name, weight in plain.state_dict().items():
        torch.testing.assert_close(graphed.state_dict()[name], weight, rtol=0, atol=0)
    windows, adjacency = inputs()
    with torch.no_grad():
        expected = plain.eval()(windows)
        got = graphed.eval()(windows, adjacency)
    torch.testing.assert_close(got, expected, rtol=0, atol=1e-6)


def test_gnn_draws_its_extra_weights_from_a_side_stream():
    """Training noise (dropout) then follows the plain model's random stream exactly."""
    build()
    after_plain = torch.get_rng_state()
    build("gnn")
    torch.testing.assert_close(torch.get_rng_state(), after_plain, rtol=0, atol=0)


@pytest.mark.parametrize("graph", ["gnn", "bias"])
def test_the_gates_switch_the_map_on(graph):
    model = build(graph).eval()
    windows, adjacency = inputs()
    with torch.no_grad():
        off = model(windows, adjacency)
        for gate in model.gate_parameters():
            gate.fill_(2.0)
        on = model(windows, adjacency)
    assert not torch.allclose(on, off)


def test_the_attention_bias_is_applied_the_same_in_training_and_prediction():
    """Prediction may take a faster attention path; it must honour the mask like training does."""
    model = build("bias", dropout=0.0)
    with torch.no_grad():
        model.attention_bias.copy_(torch.tensor([[1.5, -2.0], [0.5, 3.0]]))
    windows, adjacency = inputs()
    with torch.no_grad():
        trained_path = model.train()(windows, adjacency)
        predict_path = model.eval()(windows, adjacency)
    torch.testing.assert_close(predict_path, trained_path, rtol=1e-5, atol=1e-5)
    assert torch.backends.mha.get_fastpath_enabled(), "the global fast-path switch must be restored"


def test_a_graph_model_needs_the_map():
    with pytest.raises(ValueError, match="adjacency"):
        build("gnn")(inputs()[0])


@pytest.mark.parametrize("graph", ["gnn", "bias"])
def test_gates_learn_at_their_own_rate(graph, panel):
    """Adam's first step moves a parameter by its learning rate: 0.02 for the gates, not 1e-3."""
    skill = ITransformerSkill(
        loss="mae", path=True, features=True, graph=graph,
        input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=1,
    )
    skill.fit(truncate_panel(panel, 300))
    moved = np.abs(skill.gate_history_[-1]["gates"])
    assert moved.max() == pytest.approx(GATE_LEARNING_RATE, rel=0.01)


def test_every_refit_records_its_gates(panel):
    skill = ITransformerSkill(
        loss="mae", path=True, features=True, graph="bias",
        input_size=20, hidden_size=8, n_heads=2, d_ff=16, max_steps=3,
    )
    for position in (250, 300):
        skill.fit(truncate_panel(panel, position))
    assert [entry["refit_date"] for entry in skill.gate_history_] == [
        next(iter(panel.values())).index[p] for p in (250, 300)
    ]
    assert all(len(entry["gates"]) == 2 * 2 for entry in skill.gate_history_)  # layers x heads


def test_plain_models_record_no_gates(panel):
    skill = ITransformerSkill(loss="mae", path=True, features=True, input_size=20, hidden_size=8,
                              n_heads=2, d_ff=16, max_steps=2)
    skill.fit(truncate_panel(panel, 300))
    assert skill.gate_history_ == []


def test_summarize_gates():
    assert summarize_gates("gnn", [-0.4]) == pytest.approx(-0.4)
    assert summarize_gates("bias", [0.2, -0.4, 0.0, 0.6]) == pytest.approx(0.3)


def test_the_shuffled_map_keeps_its_statistics_but_moves_the_links():
    rng = np.random.default_rng(3)
    raw = rng.uniform(size=(10, 10)) * (rng.uniform(size=(10, 10)) < 0.3)
    matrix = np.maximum(raw, raw.T) + np.eye(10)
    matrix /= matrix.sum(axis=1, keepdims=True)
    shuffled = _shuffled(matrix)
    np.testing.assert_allclose(shuffled.sum(axis=1), 1.0)
    np.testing.assert_array_equal(np.sort(shuffled, axis=None), np.sort(matrix, axis=None))
    np.testing.assert_array_equal(shuffled > 0, (shuffled > 0).T)
    assert not np.array_equal(shuffled, matrix)
    # One fixed permutation for every date of a series.
    series = np.stack([matrix, matrix * 0.5])
    np.testing.assert_array_equal(_shuffled(series)[0], shuffled)
