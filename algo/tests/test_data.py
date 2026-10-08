from datetime import date

import numpy as np
import pandas as pd
import pytest

from tsm import data


def raw_frame(index):
    n = len(index)
    return pd.DataFrame(
        {
            "Open": np.linspace(10, 11, n),
            "High": np.linspace(11, 12, n),
            "Low": np.linspace(9, 10, n),
            "Close": np.linspace(10, 11, n),
            "Volume": [1000] * n,
            "Dividends": [0.0] * n,
            "Stock Splits": [0.0] * n,
        },
        index=index,
    )


def test_clean_prices_shape_and_index():
    index = pd.date_range("2024-01-02", periods=4, freq="B", tz="America/New_York")
    out = data.clean_prices(raw_frame(index), today=date(2024, 2, 1))
    assert list(out.columns) == ["open", "high", "low", "close", "volume"]
    assert out.index.name == "date"
    assert out.index.tz is None
    assert out.index[0] == pd.Timestamp("2024-01-02")


def test_clean_prices_sorts_and_drops_bad_rows():
    index = pd.to_datetime(["2024-01-04", "2024-01-02", "2024-01-03", "2024-01-03", "2024-01-05"])
    raw = raw_frame(index)
    raw.iloc[0, raw.columns.get_loc("Close")] = np.nan  # 2024-01-04: missing close
    raw.iloc[4, raw.columns.get_loc("Close")] = 0.0  # 2024-01-05: impossible price
    out = data.clean_prices(raw, today=date(2024, 2, 1))
    assert out.index.tolist() == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert out.index.is_unique and out.index.is_monotonic_increasing


def test_clean_prices_drops_today():
    index = pd.to_datetime(["2024-01-02", "2024-01-03"])
    out = data.clean_prices(raw_frame(index), today=date(2024, 1, 3))
    assert out.index.tolist() == [pd.Timestamp("2024-01-02")]


def test_clean_prices_rejects_missing_columns():
    raw = raw_frame(pd.to_datetime(["2024-01-02"])).drop(columns=["Close"])
    with pytest.raises(ValueError, match="close"):
        data.clean_prices(raw)


def test_load_prices_downloads_once_then_uses_cache(tmp_path, monkeypatch):
    calls = []

    def fake_download(ticker, start):
        calls.append(ticker)
        return raw_frame(pd.to_datetime(["2024-01-02", "2024-01-03"]))

    monkeypatch.setattr(data, "_download", fake_download)
    first = data.load_prices("AAPL", data_dir=tmp_path)
    second = data.load_prices("AAPL", data_dir=tmp_path)
    assert calls == ["AAPL"]
    pd.testing.assert_frame_equal(first, second, check_freq=False)

    data.load_prices("AAPL", data_dir=tmp_path, refresh=True)
    assert calls == ["AAPL", "AAPL"]


def test_load_prices_rejects_unknown_ticker(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "_download", lambda ticker, start: raw_frame(pd.DatetimeIndex([])))
    with pytest.raises(ValueError, match="no price data"):
        data.load_prices("NOPE", data_dir=tmp_path)
    assert not (tmp_path / "NOPE.csv").exists()


def test_align_and_truncate_panel():
    a = data.clean_prices(raw_frame(pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])), today=date(2024, 2, 1))
    b = data.clean_prices(raw_frame(pd.to_datetime(["2024-01-03", "2024-01-04", "2024-01-05"])), today=date(2024, 2, 1))
    panel = data.align_panel({"A": a, "B": b})
    assert panel["A"].index.equals(panel["B"].index)
    assert panel["A"].index.tolist() == [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-04")]
    cut = data.truncate_panel(panel, 0)
    assert all(frame.index[-1] == pd.Timestamp("2024-01-03") for frame in cut.values())
