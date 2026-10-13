"""Earnings dates: parsing both sources, the checks, and the loader. No network."""
import numpy as np
import pandas as pd
import pytest

from tsm import earnings


def test_ciks_match_brk_b_written_either_way():
    listing = {
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1067983, "ticker": "BRK.B", "title": "Berkshire Hathaway"},
    }
    assert earnings.sec_ciks(listing, ["AAPL", "BRK-B", "NOPE"]) == {"AAPL": 320193, "BRK-B": 1067983}


def test_parse_8k_keeps_only_8k_rows():
    block = {
        "form": ["4", "8-K", "10-Q", "8-K/A"],
        "filingDate": ["2024-01-02", "2024-01-25", "2024-02-01", "2024-01-26"],
        "reportDate": ["", "2024-01-25", "2023-12-31", "2024-01-25"],
        "acceptanceDateTime": ["", "2024-01-25T16:05:00.000Z", "", "2024-01-26T09:00:00.000Z"],
        "items": ["", "2.02,9.01", "", "2.02"],
        "accessionNumber": ["a", "b", "c", "d"],
    }
    rows = earnings.parse_8k(block, "AAPL", 320193)
    assert rows["accession"].tolist() == ["b", "d"]
    assert set(rows["ticker"]) == {"AAPL"} and set(rows["cik"]) == {320193}


def test_a_release_is_an_original_8k_with_item_2_02():
    sec = pd.DataFrame(
        {
            "ticker": ["X"] * 5,
            "form": ["8-K", "8-K", "8-K/A", "8-K", "8-K"],
            "filing_date": ["2024-01-25", "2024-02-10", "2024-01-26", "2024-04-25", "2024-04-25"],
            "items": ["2.02,9.01", "7.01,9.01", "2.02", "9.01,2.02", "2.02"],
        }
    )
    dates = earnings.results_dates(sec)["date"].dt.strftime("%Y-%m-%d").tolist()
    assert dates == ["2024-01-25", "2024-04-25"]  # Reg FD and the amendment out, one row per day


@pytest.mark.parametrize(
    "moment, timing",
    [
        ("2024-01-25 06:00", "before_open"),
        ("2024-01-25 09:29", "before_open"),
        ("2024-01-25 09:30", "during"),
        ("2024-01-25 16:00", "after_close"),
        ("2024-01-25 00:00", "unknown"),
    ],
)
def test_timing_of_a_release(moment, timing):
    assert earnings.timing_of(pd.Timestamp(moment, tz="America/New_York")) == timing


def test_timing_reads_new_york_time_whatever_the_zone():
    assert earnings.timing_of(pd.Timestamp("2024-01-25 21:05", tz="UTC")) == "after_close"  # 16:05 in New York


def test_parse_yahoo():
    index = pd.DatetimeIndex(["2024-04-25 16:30", "2024-01-25 06:00"], tz="America/New_York", name="Earnings Date")
    frame = pd.DataFrame({"EPS Estimate": [1.0, 0.9], "Reported EPS": [1.1, np.nan], "Surprise(%)": [10.0, np.nan]}, index=index)
    rows = earnings.parse_yahoo(frame, "AAPL")
    assert rows["datetime"].tolist() == ["2024-04-25 16:30", "2024-01-25 06:00"]
    assert rows["timing"].tolist() == ["after_close", "before_open"]
    assert rows["eps_estimate"].tolist() == [1.0, 0.9]
    assert earnings.parse_yahoo(None, "SPY").empty


def test_a_weekend_release_reacts_on_monday():
    days = pd.bdate_range("2024-01-01", "2024-01-31")
    saturday = pd.Series(pd.to_datetime(["2024-01-06"]))
    assert days[earnings.to_trading_day(saturday, days)[0]] == pd.Timestamp("2024-01-08")


def test_quarter_counts_skip_the_quarter_that_is_not_over():
    dates = pd.Series(pd.to_datetime(["2024-01-25", "2024-02-10", "2024-07-25", "2024-10-03"]))
    counts = earnings.quarter_counts(dates, "2024-01-01", "2024-10-07")
    assert counts.index.astype(str).tolist() == ["2024Q1", "2024Q2", "2024Q3"]  # Q4 has only begun
    assert counts.tolist() == [2, 0, 1]


def test_agreement_is_within_one_trading_day_and_only_where_both_cover():
    days = pd.bdate_range("2024-01-01", "2024-12-31")
    mine = pd.Series(pd.to_datetime(["2024-01-25", "2024-04-25", "2024-07-25", "2024-10-24"]))
    theirs = pd.Series(pd.to_datetime(["2024-01-26", "2024-04-29", "2024-07-25"]))  # +1, +2, same day
    # 2024-10-24 is after the other source ends, so it is not counted against it.
    assert earnings.agreement(mine, theirs, days) == pytest.approx(2 / 3)
    assert np.isnan(earnings.agreement(mine, theirs.iloc[:0], days))


def test_the_reaction_check_sees_moves_on_release_days():
    days = pd.bdate_range("2023-01-02", periods=400)
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, len(days))
    releases = days[[50, 150, 250, 350]]
    returns[[51, 151, 251, 351]] = 0.08  # after the close: the move shows the next day
    close = pd.Series(100 * np.exp(np.cumsum(returns)), index=days)
    out = earnings.reaction(close, pd.Series(releases))
    assert out["events"] == 4
    assert out["event_move"] == pytest.approx(0.08, rel=1e-6)
    assert out["ordinary_day"] < out["ordinary_pair"] < 0.02  # the release days are left out of both


def test_load_earnings_reads_what_was_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(earnings, "SEC_FILE", tmp_path / "sec.csv")
    monkeypatch.setattr(earnings, "YAHOO_FILE", tmp_path / "yahoo.csv")
    pd.DataFrame({"ticker": ["X"], "cik": [1], "form": ["8-K"], "filing_date": ["2024-01-25"], "items": ["2.02"]}).to_csv(
        tmp_path / "sec.csv", index=False
    )
    pd.DataFrame({"ticker": ["X"], "datetime": ["2024-01-25 16:30"], "timing": ["after_close"]}).to_csv(
        tmp_path / "yahoo.csv", index=False
    )
    sec, yahoo = earnings.load_earnings("sec"), earnings.load_earnings("yahoo")
    assert sec["date"].iloc[0] == pd.Timestamp("2024-01-25") and sec["items"].iloc[0] == "2.02"
    assert yahoo["date"].iloc[0] == pd.Timestamp("2024-01-25")
    assert yahoo["datetime"].iloc[0] == pd.Timestamp("2024-01-25 16:30")
    with pytest.raises(ValueError, match="sec' or 'yahoo"):
        earnings.load_earnings("other")


def test_sec_needs_a_contact_email_before_any_request(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "no email here")
    monkeypatch.setattr(earnings, "_sec_get", lambda *a, **k: pytest.fail("no request without a contact email"))
    with pytest.raises(RuntimeError, match="contact email"):
        earnings.fetch_sec(["AAPL"])


def test_spy_reports_no_earnings():
    assert "SPY" not in earnings.covered_tickers() and len(earnings.covered_tickers()) == 51
