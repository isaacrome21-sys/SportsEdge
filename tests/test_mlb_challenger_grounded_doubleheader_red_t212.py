"""RED (t212 audit of ad842a03): real doubleheaders with a quick game 1 must
pass via grounded fixture identity (statsapi gameNumber / doubleHeader, or a
recorded game end), while re-listings and impossible overlaps still refuse.
final_observed (an ingest time) is never used."""
from datetime import timedelta

import pytest

from sportsedge.research.mlb_total_offense_defense_challenger import (
    MLBTotalCandidateError, parse_finals)
from test_mlb_total_offense_defense_challenger import BASE, sample_games

DAY = BASE + timedelta(days=500)


def _g(eid, away, home, start_min, **extra):
    start = DAY + timedelta(minutes=start_min)
    row = {"event_id": eid, "away_id": away, "home_id": home,
           "event_start_ts": start.isoformat(),
           "final_observed_ts": (start + timedelta(days=2)).isoformat(),  # late ingest
           "status": "FINAL", "away_runs": 3, "home_runs": 4}
    row.update(extra)
    return row


def _load(rows):
    return parse_finals(sample_games() + rows)


@pytest.mark.parametrize("gap", [175, 165, 179])  # 2h20/2h55, 2h10/2h45, 3h/179m
def test_real_doubleheader_with_game_numbers_passes(gap):
    rows = [_g("d1", "NYY", "BOS", 0, gameNumber=1, doubleHeader="Y"),
            _g("d2", "NYY", "BOS", gap, gameNumber=2, doubleHeader="Y")]
    assert len(_load(rows)) == 202


@pytest.mark.parametrize("dur,gap", [(140, 175), (130, 165), (160, 179)])
def test_real_doubleheader_with_recorded_game_end_passes(dur, gap):
    start = DAY
    rows = [_g("e1", "NYY", "BOS", 0,
               game_end_ts=(start + timedelta(minutes=dur)).isoformat()),
            _g("e2", "NYY", "BOS", gap)]
    assert len(_load(rows)) == 202


def test_duration_field_also_grounds():
    rows = [_g("u1", "NYY", "BOS", 0, game_duration_minutes=140),
            _g("u2", "NYY", "BOS", 175)]
    assert len(_load(rows)) == 202


def test_split_doubleheader_without_fields_passes():
    rows = [_g("s1", "TOR", "BAL", 0), _g("s2", "TOR", "BAL", 360)]
    assert len(_load(rows)) == 202


def test_relisting_same_game_number_refused():
    rows = [_g("r1", "NYY", "BOS", 0, gameNumber=1), _g("r2", "NYY", "BOS", 120, gameNumber=1)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


def test_relisting_without_grounding_inside_180_refused():
    rows = [_g("r1", "NYY", "BOS", 0), _g("r2", "NYY", "BOS", 175)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


def test_game_numbers_under_90_minute_floor_refused():
    rows = [_g("f1", "NYY", "BOS", 0, gameNumber=1), _g("f2", "NYY", "BOS", 80, gameNumber=2)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


def test_descending_game_numbers_refused():
    rows = [_g("x1", "NYY", "BOS", 0, gameNumber=2), _g("x2", "NYY", "BOS", 175, gameNumber=1)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


def test_different_opponent_within_180_refused_even_with_game_numbers():
    rows = [_g("o1", "NYY", "BOS", 0, gameNumber=1), _g("o2", "TOR", "NYY", 175, gameNumber=2)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


def test_recorded_end_after_next_start_refused():
    rows = [_g("v1", "NYY", "BOS", 0, game_end_ts=(DAY + timedelta(minutes=200)).isoformat()),
            _g("v2", "NYY", "BOS", 175)]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


def test_doubleheader_flag_N_does_not_ground():
    rows = [_g("n1", "NYY", "BOS", 0, gameNumber=1, doubleHeader="N"),
            _g("n2", "NYY", "BOS", 175, gameNumber=2, doubleHeader="N")]
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


@pytest.mark.parametrize("bad", [0, 4, True, "x", 1.5])
def test_invalid_game_number_refused(bad):
    with pytest.raises(MLBTotalCandidateError, match="GAME_NUMBER_INVALID"):
        _load([_g("b1", "NYY", "BOS", 0, gameNumber=bad)])


def test_final_observed_is_not_a_game_end():
    # final_observed 2 days late must not create a false overlap; a split
    # doubleheader still passes.
    rows = [_g("l1", "TOR", "BAL", 0), _g("l2", "TOR", "BAL", 300)]
    assert len(_load(rows)) == 202
