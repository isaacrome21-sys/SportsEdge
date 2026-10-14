"""CBB team-ID / fixture binding and ID-based Illinois exclusion (offline)."""
from datetime import datetime, timezone

import pytest

from sportsedge.sports.cbb.identity import CBBIdentityError, bind_fixture, resolve_team

AS_OF = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
DIR = {"sports": [{"leagues": [{"teams": [{"team": t} for t in [
    {"id": "57", "displayName": "Florida Gators", "shortDisplayName": "Florida", "abbreviation": "FLA",
     "location": "Florida", "name": "Gators"},
    {"id": "2226", "displayName": "Florida Atlantic Owls", "shortDisplayName": "FAU", "abbreviation": "FAU",
     "location": "Florida Atlantic", "name": "Owls"},
    {"id": "2130", "displayName": "Chicago State Cougars", "shortDisplayName": "Chicago St",
     "abbreviation": "CHIC", "location": "Chicago State", "name": "Cougars"},
    {"id": "305", "displayName": "DePaul Blue Demons", "shortDisplayName": "DePaul", "abbreviation": "DEP",
     "location": "DePaul", "name": "Blue Demons"},
    {"id": "77", "displayName": "Northwestern Wildcats", "shortDisplayName": "Northwestern",
     "abbreviation": "NU", "location": "Northwestern", "name": "Wildcats"},
    {"id": "2466", "displayName": "Northwestern State Demons", "shortDisplayName": "Northwestern St",
     "abbreviation": "NWST", "location": "Northwestern State", "name": "Demons"},
    {"id": "150", "displayName": "Duke Blue Devils", "shortDisplayName": "Duke", "abbreviation": "DUKE",
     "location": "Duke", "name": "Blue Devils"},
]]}]}]}


def sb(home="150", away="57", date="2026-11-11T00:00Z", extra=()):
    ev = [{"id": "401", "date": date, "competitions": [{"neutralSite": False, "competitors": [
        {"homeAway": "home", "team": {"id": home}}, {"homeAway": "away", "team": {"id": away}}]}]}]
    return {"events": ev + list(extra)}


def bind(away, home, board, start="2026-11-11T00:00:00Z", as_of=AS_OF):
    return bind_fixture(DIR, board, away=away, home=home, start=start, as_of=as_of)


def test_exact_unique_resolution_and_no_cross_school_match():
    assert resolve_team(DIR, "Florida")["id"] == "57"
    assert resolve_team(DIR, "Florida Atlantic Owls")["id"] == "2226"
    with pytest.raises(CBBIdentityError, match="NOT_UNIQUELY"):
        resolve_team(DIR, "Flor")


def test_bind_fixture_by_ids_and_start():
    b = bind("Florida Gators", "Duke", sb(), start="2026-11-11T00:05:00Z")
    assert b["event_id"] == "401" and b["playable_status"] == "RESEARCH_ONLY" and b["play_authority"] is False


def test_swapped_slots_wrong_time_duplicates_and_started_fail_closed():
    with pytest.raises(CBBIdentityError, match="FIXTURE_NOT_UNIQUELY"):
        bind("Florida", "Duke", sb(home="57", away="150"))
    with pytest.raises(CBBIdentityError, match="FIXTURE_NOT_UNIQUELY"):
        bind("Florida", "Duke", sb(), start="2026-11-11T01:00:00Z")
    dup = sb()["events"][0] | {"id": "402"}
    with pytest.raises(CBBIdentityError, match="FIXTURE_NOT_UNIQUELY"):
        bind("Florida", "Duke", sb(extra=[dup]))
    with pytest.raises(CBBIdentityError, match="STARTED"):
        bind("Florida", "Duke", sb(), as_of=datetime(2026, 11, 11, 1, tzinfo=timezone.utc))


@pytest.mark.parametrize("name", ["Chicago State", "Chicago St", "CHIC", "Chicago State Cougars"])
def test_illinois_excluded_by_espn_id_any_name_form(name):
    b = bind(name, "Duke", sb(home="150", away="2130"))
    assert b["playable_status"] == "BLOCKED" and b["reason"] == "ILLINOIS_COLLEGE_EXCLUDED"


def test_illinois_home_team_excluded_too():
    b = bind("Duke", "DePaul", sb(home="305", away="150"))
    assert b["playable_status"] == "BLOCKED" and b["excluded_teams"] == ["DePaul Blue Demons"]


def test_northwestern_state_distinct_from_northwestern():
    assert resolve_team(DIR, "Northwestern State")["illinois_excluded"] is False
    assert resolve_team(DIR, "Northwestern")["illinois_excluded"] is True
    assert bind("Northwestern St", "Duke", sb(away="2466"))["playable_status"] == "RESEARCH_ONLY"



@pytest.mark.parametrize("bad_id", [None, "", "None", 0, True, -1, "abc", "0" * 5000, "١٢٣"])
def test_missing_or_nonpositive_event_ids_never_bind(bad_id):
    event = sb()["events"][0]
    event["id"] = bad_id
    with pytest.raises(CBBIdentityError, match="FIXTURE_NOT_UNIQUELY_VERIFIED:0"):
        bind("Florida", "Duke", {"events": [event]})


def test_duplicate_home_competitor_is_not_last_wins(tmp_path=None):
    event = sb()["events"][0]
    event["competitions"][0]["competitors"].insert(
        0, {"homeAway": "home", "team": {"id": "2130"}})
    with pytest.raises(CBBIdentityError, match="FIXTURE_NOT_UNIQUELY_VERIFIED:0"):
        bind("Florida", "Duke", {"events": [event]})


@pytest.mark.parametrize("as_of", [None, "2026-11-10T12:00:00Z",
                                  datetime(2026, 11, 10, 12),
                                  datetime(2026, 11, 10, 12, tzinfo=None)])
def test_as_of_must_be_aware_datetime(as_of):
    with pytest.raises(CBBIdentityError, match="AS_OF_TIMEZONE_REQUIRED"):
        bind("Florida", "Duke", sb(), as_of=as_of)


@pytest.mark.parametrize("events", [None, "bad", {}, [None], ["bad"], [0], [True]])
def test_missing_or_malformed_scoreboard_events_fail_safely(events):
    if not isinstance(events, list):
        with pytest.raises(CBBIdentityError, match="SCOREBOARD_EVENTS_INVALID"):
            bind("Florida", "Duke", {"events": events})
    else:
        with pytest.raises(CBBIdentityError, match="FIXTURE_NOT_UNIQUELY_VERIFIED:0"):
            bind("Florida", "Duke", {"events": events})
