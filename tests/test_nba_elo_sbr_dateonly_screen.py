"""Date-only NBA Elo diagnostics must not fabricate historical PIT/close."""
from datetime import date, timedelta
import pytest

from scripts.research_nba_elo_sbr_dateonly_screen import (
    evaluate_date_only, normalize, verify_source_blob,
)


def fixture(day, h, a, hp=110, ap=100, **quotes):
    return {"season": int(day[:4]), "date": float(day.replace("-", "")),
            "home_team": h, "away_team": a,
            "home_final": str(hp), "away_final": str(ap),
            **quotes}


def sample():
    start = date(2014, 3, 1)
    rows = []
    for i in range(18):
        day = str(start + timedelta(days=i))
        rows.append(fixture(day, "A", "B" if i % 2 else "C",
                            110, 100))
    rows.append(fixture("2015-01-05", "A", "B", 112, 100,
                        home_close_spread=-4.5,
                        home_close_ml=-135, away_close_ml=125))
    rows.append(fixture("2015-01-05", "A", "C", 120, 100,
                        home_close_spread=-6.5,
                        home_close_ml=-160, away_close_ml=145))
    return rows


def test_holdout_with_real_prior_dates_and_unadmitted_market_fields():
    r = evaluate_date_only(sample(), first=2015, last=2015)
    assert r["model_games"] == 2
    assert r["spread_reference_games"] == 2
    assert r["moneyline_reference_games"] == 2
    assert r["spread_reference_distinct_days"] == 1
    assert r["model_moneyline_brier_paired"] is not None
    assert r["market_reference_authority"] == "INDICATIVE_NOT_ADMITTED"
    assert r["play_authority"] is False


def test_same_date_outcome_does_not_leak_into_second_prediction():
    rows = sample()
    before = evaluate_date_only(rows, first=2015, last=2015,
                                include_rows=True)["rows"]
    rows[-2]["home_final"] = "190"
    rows[-2]["away_final"] = "80"
    after = evaluate_date_only(rows, first=2015, last=2015,
                               include_rows=True)["rows"]
    assert before[1]["margin_error"] == after[1]["margin_error"]
    assert before[1]["ml_brier"] == after[1]["ml_brier"]


def test_missing_archive_moneylines_do_not_become_market_pricing():
    rows = sample()
    for row in rows:
        row.pop("home_close_ml", None)
        row.pop("away_close_ml", None)
    r = evaluate_date_only(rows, first=2015, last=2015)
    assert r["moneyline_reference_games"] == 0
    assert r["indicative_market_moneyline_brier"] is None


def test_malformed_calendar_date_fails_closed():
    rows = sample()
    rows[0]["date"] = 20141399.0
    with pytest.raises(ValueError, match="CALENDAR_DATE_INVALID"):
        normalize(rows)


def test_git_blob_must_match_exact_source():
    with pytest.raises(ValueError, match="BLOB_MISMATCH"):
        verify_source_blob(b"not the source")


def test_duplicate_date_fixture_cannot_be_double_counted():
    rows = sample()
    rows.append(dict(rows[-1]))
    with pytest.raises(ValueError, match="DUPLICATE_GAME"):
        normalize(rows)
