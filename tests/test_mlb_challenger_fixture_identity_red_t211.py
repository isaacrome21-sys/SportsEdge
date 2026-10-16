"""RED (t211u, #2357): one real fixture under two event ids must not be
double counted (history or prequential trials)."""
from datetime import timedelta

import pytest

from sportsedge.research.mlb_total_offense_defense_challenger import (
    MLBTotalCandidateError, parse_finals, predict_total, prequential_backtest)
from test_mlb_total_offense_defense_challenger import BASE, sample_games, target


def _dup(games, i=5, **chg):
    row = dict(games[i], event_id=f"dup-of-{i}")
    row.update(chg)
    return games + [row]


def test_same_fixture_different_event_id_refused():
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(_dup(sample_games()))


def test_same_fixture_case_or_space_variant_team_ids_refused():
    g = sample_games()
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(_dup(g, i=4, away_id=" a ", home_id="b"))


def test_team_in_two_games_at_same_start_refused():
    g = sample_games()
    row = dict(g[4], event_id="clash", away_id="A", home_id="Z")
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        parse_finals(g + [row])


def test_backtest_refuses_duplicate_fixture():
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        prequential_backtest(_dup(sample_games(), i=190),
                             holdout_from=(BASE + timedelta(days=180)).isoformat())


def test_doubleheader_distinct_starts_still_allowed():
    g = sample_games()
    row = dict(g[4], event_id="dh2",
               event_start_ts=(BASE + timedelta(days=4, hours=5)).isoformat(),
               final_observed_ts=(BASE + timedelta(days=4, hours=9)).isoformat())
    assert len(parse_finals(g + [row])) == len(g) + 1
    predict_total(g + [row], target())
