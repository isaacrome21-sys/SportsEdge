"""The date-only archive screen refuses claims it cannot prove."""
from datetime import date,timedelta
import pytest
from scripts.research_nba_v2_sbr_dateonly_screen import (
    evaluate_calendar_archive, verify_archive_blob, SOURCE_BLOB_SHA1
)


def synthetic():
    out=[]
    for i in range(70):
        day=int((date(2015,1,1)+timedelta(days=i)).strftime("%Y%m%d"))
        out.append({"season":2015,"date":day,
            "home_team":"A" if i%2 else "B",
            "away_team":"B" if i%2 else "A",
            "home_final":"110","away_final":"100",
            "close_over_under":211.5})
    return out


def test_date_only_screen_no_valid_market_authority():
    out=evaluate_calendar_archive(synthetic(),begin=2015,end=2015)
    assert out["model_scored_games"]>0
    assert out["paired_games"]==out["model_scored_games"]
    assert out["market_vintage"]=="UNKNOWN_NOT_ADMITTED"
    assert out["promotion_authority"] is False
    assert out["model_under_reference"]==out["paired_games"]


def test_inserting_same_date_outcome_cannot_be_used_as_prior():
    raw=synthetic()
    original=evaluate_calendar_archive(raw,begin=2015,end=2015)
    # A massive new future SAME-DAY result may change summary membership
    # but the construction never includes its score as a prior that day.
    row={**raw[-1],"home_team":"C","away_team":"D",
         "home_final":"250","away_final":"250"}
    alt=evaluate_calendar_archive(raw+[row],begin=2015,end=2015)
    assert alt["strict_prior_dates_only"]
    assert alt["model_scored_games"]==original["model_scored_games"]


def test_duplicate_game_refuses():
    raw=synthetic()
    with pytest.raises(ValueError,match="DUPLICATE_FIXTURE"):
        evaluate_calendar_archive(raw+[raw[0]],begin=2015,end=2015)


def test_non_calendar_day_refuses():
    data=synthetic()
    data[0]["date"]=20150165
    with pytest.raises(ValueError,match="CALENDAR_DATE_INVALID"):
        evaluate_calendar_archive(data,begin=2015,end=2015)


def test_incorrect_bytes_cannot_be_called_source_pin():
    with pytest.raises(ValueError,match="BLOB_PIN_MISMATCH"):
        verify_archive_blob(b"[]")
    assert len(SOURCE_BLOB_SHA1)==40



def test_fixed_season_breakdown_reconciles_to_whole_holdout():
    raw=synthetic()
    # Two nonoverlapping genuine calendar cohorts; this test is synthetic
    # and grants no historical price/source authentication.
    for g in synthetic():
        y={**g}
        y["season"]=2016
        y["date"]+=10000
        raw.append(y)
    out=evaluate_calendar_archive(raw,begin=2015,end=2016)
    parts=out["all_seasons_indicative_breakdown"]
    assert [b["season"] for b in parts]==[2015,2016]
    assert sum(b["paired_games"] for b in parts)==out["paired_games"]
    assert sum(b["model_under_reference"] for b in parts)==out["model_under_reference"]
    assert sum(b["model_over_reference"] for b in parts)==out["model_over_reference"]
    assert out["subcohort_selection_authority"]=="NONE_PREDECLARED_DESCRIPTIVE_ONLY"
    assert all(b["market_admission"]=="NOT_VERIFIED" and
               b["eligible_for_card"] is False for b in parts)


def test_missing_reference_stays_unmeasured_in_season_diagnostics():
    raw=synthetic()
    for g in raw:
        g["close_over_under"]=None
    out=evaluate_calendar_archive(raw,begin=2015,end=2015)
    assert out["paired_games"]==0
    assert out["all_seasons_indicative_breakdown"]==[]
    assert out["indicative_reference_screen"]=="REFERENCE_UNMEASURED"
