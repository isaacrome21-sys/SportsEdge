"""RED (t212 audit, #2357): same-team overlap window, canonical team aliases,
real doubleheaders still pass."""
from datetime import timedelta

import pytest

from sportsedge.research.mlb_total_offense_defense_challenger import (
    MLBTotalCandidateError, canonical_team_id, parse_finals)
from test_mlb_total_offense_defense_challenger import BASE, sample_games


def _game(eid, away, home, start, hours=3):
    return {"event_id": eid, "away_id": away, "home_id": home,
            "event_start_ts": start.isoformat(),
            "final_observed_ts": (start + timedelta(hours=hours)).isoformat(),
            "status": "FINAL", "away_runs": 3, "home_runs": 4}


DAY = BASE + timedelta(days=500)


@pytest.mark.parametrize("minutes", [1, 5, 30, 60])
def test_same_fixture_minutes_apart_refused(minutes):
    g = [_game("x1", "NYY", "BOS", DAY), _game("x2", "NYY", "BOS", DAY + timedelta(minutes=minutes))]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(sample_games() + g)


def test_team_in_overlapping_games_refused():
    g = [_game("x1", "NYY", "BOS", DAY), _game("x2", "TOR", "NYY", DAY + timedelta(minutes=45))]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(sample_games() + g)


@pytest.mark.parametrize("a,b", [("NYY", "New York Yankees"), ("CWS", "CHW"), ("AZ", "ARI"),
                                 ("WSH", "WSN"), ("OAK", "ATH"), ("SD", "SDP"), ("KC", "KCR"),
                                 ("TB", "TBR"), ("SF", "SFG"), ("LAA", "ANA"), ("Yankees", "nyy")])
def test_aliases_normalize_to_one_canonical_id(a, b):
    assert canonical_team_id(a) == canonical_team_id(b)


def test_alias_duplicate_fixture_refused():
    g = [_game("x1", "NYY", "BOS", DAY), _game("x2", "New York Yankees", "Boston Red Sox", DAY)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(sample_games() + g)


def test_distinct_teams_not_merged():
    assert canonical_team_id("NYY") != canonical_team_id("NYM")
    assert canonical_team_id("LAD") != canonical_team_id("LAA")
    assert canonical_team_id("CHC") != canonical_team_id("CWS")


def test_real_doubleheaders_still_pass():
    traditional = [_game("d1", "NYY", "BOS", DAY, hours=3),
                   _game("d2", "NYY", "BOS", DAY + timedelta(hours=3, minutes=35), hours=3)]
    split = [_game("s1", "TOR", "BAL", DAY, hours=3),
             _game("s2", "TOR", "BAL", DAY + timedelta(hours=6), hours=3)]
    assert len(parse_finals(sample_games() + traditional + split)) == 204


# --- t212 follow-up: 180-minute same-club window; NY short forms ------------
@pytest.mark.parametrize("minutes", [100, 150, 179])
def test_second_game_within_180_minutes_refused(minutes):
    g = [_game("w1", "NYY", "BOS", DAY), _game("w2", "TOR", "NYY", DAY + timedelta(minutes=minutes))]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(sample_games() + g)


@pytest.mark.parametrize("a,b", [("NY Yankees", "NYY"), ("NY Mets", "NYM"),
                                 ("LA Dodgers", "LAD"), ("LA Angels", "LAA"),
                                 ("Chi Cubs", "CHC"), ("Chi White Sox", "CWS"),
                                 ("St. Louis Cardinals", "STL")])
def test_common_short_forms_alias(a, b):
    assert canonical_team_id(a) == canonical_team_id(b)
