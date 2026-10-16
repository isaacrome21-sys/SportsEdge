"""RED (t212 audit of f766c57a): spoofed doubleheaders refuse.  doubleHeader
must be Y or S and identical on both games, gameNumber exactly 1 then 2; a
recorded end binds even with gameNumber; the 90-minute floor is absolute."""
from datetime import timedelta

import pytest

from sportsedge.research.mlb_total_offense_defense_challenger import (
    MLBTotalCandidateError, parse_finals)
from test_mlb_challenger_grounded_doubleheader_red_t212 import DAY, _g, _load


def _refused(rows):
    with pytest.raises(MLBTotalCandidateError, match="DUPLICATE_FIXTURE_IDENTITY"):
        _load(rows)


@pytest.mark.parametrize("f1,f2", [(None, None), ("Y", None), (None, "Y"),
                                   ("Y", "S"), ("S", "Y")])
def test_doubleheader_flag_missing_or_mismatched_refused(f1, f2):
    a = {"gameNumber": 1}
    b = {"gameNumber": 2}
    if f1:
        a["doubleHeader"] = f1
    if f2:
        b["doubleHeader"] = f2
    _refused([_g("a", "NYY", "BOS", 0, **a), _g("b", "NYY", "BOS", 175, **b)])


@pytest.mark.parametrize("n1,n2", [(1, 3), (2, 3)])
def test_game_numbers_must_be_exactly_1_then_2(n1, n2):
    _refused([_g("a", "NYY", "BOS", 0, gameNumber=n1, doubleHeader="Y"),
              _g("b", "NYY", "BOS", 175, gameNumber=n2, doubleHeader="Y")])


@pytest.mark.parametrize("flag", ["Y", "S"])
def test_valid_y_or_s_doubleheader_passes(flag):
    rows = [_g("a", "NYY", "BOS", 0, gameNumber=1, doubleHeader=flag),
            _g("b", "NYY", "BOS", 175, gameNumber=2, doubleHeader=flag)]
    assert len(_load(rows)) == 202


def test_recorded_end_binds_even_with_game_numbers():
    _refused([_g("a", "NYY", "BOS", 0, gameNumber=1, doubleHeader="Y",
                 game_end_ts=(DAY + timedelta(minutes=200)).isoformat()),
              _g("b", "NYY", "BOS", 175, gameNumber=2, doubleHeader="Y")])
    _refused([_g("a", "NYY", "BOS", 0, gameNumber=1, doubleHeader="Y",
                 game_duration_minutes=190),
              _g("b", "NYY", "BOS", 175, gameNumber=2, doubleHeader="Y")])


def test_recorded_end_consistent_with_doubleheader_passes():
    rows = [_g("a", "NYY", "BOS", 0, gameNumber=1, doubleHeader="Y",
               game_duration_minutes=140),
            _g("b", "NYY", "BOS", 175, gameNumber=2, doubleHeader="Y")]
    assert len(_load(rows)) == 202


@pytest.mark.parametrize("dur,gap", [(30, 45), (60, 89), (5, 10)])
def test_duration_cannot_beat_90_minute_floor(dur, gap):
    _refused([_g("a", "NYY", "BOS", 0, game_duration_minutes=dur),
              _g("b", "NYY", "BOS", gap)])
    _refused([_g("a", "NYY", "BOS", 0, gameNumber=1, doubleHeader="Y",
                 game_duration_minutes=dur),
              _g("b", "NYY", "BOS", gap, gameNumber=2, doubleHeader="Y")])


@pytest.mark.parametrize("end_kw", [{"game_duration_minutes": 140},
                                    {"game_end_ts": (DAY + timedelta(minutes=100)).isoformat()}])
@pytest.mark.parametrize("gap", [175, 150, 179])
def test_different_opponent_needs_180_even_with_recorded_end(end_kw, gap):
    _refused([_g("a", "NYY", "BOS", 0, **end_kw), _g("b", "TOR", "NYY", gap)])


def test_different_opponent_at_180_with_end_passes():
    rows = [_g("a", "NYY", "BOS", 0, game_duration_minutes=140), _g("b", "TOR", "NYY", 180)]
    assert len(_load(rows)) == 202
