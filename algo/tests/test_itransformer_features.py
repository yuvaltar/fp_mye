"""The two extra channels of itransformer_path_feats6: overnight gap and log VIX."""
import numpy as np
import pytest

from tsm.data import truncate_panel
from tsm.models.itransformer import ITransformerSkill, feature_series, feature_tail

ROWS = 30


def test_the_two_channels_are_the_gap_and_the_log_vix(panel):
    tail = feature_tail(panel, ROWS, gap_vix=True)
    assert tail.shape == (ROWS, len(panel), 6)
    for i, frame in enumerate(panel.values()):
        gap = np.log(frame["open"].to_numpy()[-ROWS:] / frame["close"].to_numpy()[-ROWS - 1 : -1])
        np.testing.assert_allclose(tail[:, i, 4], gap)
        np.testing.assert_allclose(tail[:, i, 5], np.log(frame["vix"].to_numpy()[-ROWS:]))
    # The first four channels are path_feats's, untouched.
    np.testing.assert_array_equal(tail[..., :4], feature_tail(panel, ROWS))


def test_series_and_tail_agree(panel):
    """fit builds the series, predict the tail; on the same day they must say the same thing."""
    series = feature_series(panel, gap_vix=True)
    assert series.shape == (len(panel["AAA"]), len(panel), 6)
    np.testing.assert_allclose(series[-ROWS:], feature_tail(panel, ROWS, gap_vix=True), rtol=1e-12, atol=1e-12)
    assert np.isnan(series[0, :, 4]).all()  # no gap before the second day
    np.testing.assert_array_equal(series[..., :4], feature_series(panel), strict=True)


def test_later_prices_do_not_change_earlier_channels(panel):
    cut = truncate_panel(panel, 250)
    np.testing.assert_array_equal(feature_series(panel, gap_vix=True)[:251], feature_series(cut, gap_vix=True))


def test_a_panel_without_vix_says_where_it_comes_from(panel):
    without = {ticker: frame.drop(columns="vix") for ticker, frame in panel.items()}
    with pytest.raises(KeyError, match="frozen \\^VIX cache"):
        feature_tail(without, ROWS, gap_vix=True)


def test_gap_vix_needs_the_four_channels():
    with pytest.raises(ValueError, match="features=True"):
        ITransformerSkill(gap_vix=True)
