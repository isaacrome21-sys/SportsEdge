from __future__ import annotations

import pytest

from sportsedge.core.simulate.nfl_probability_markets import (
    derive_anytime_touchdown_probability,
    derive_two_plus_touchdown_probability,
)


class Profile:
    def __init__(self, player_id="p1", active=True):
        self.player_id=player_id; self.active=active; self.team="H"; self.position="RB"


class Usage:
    def __init__(self, profile):
        self.players=(profile,)


class Base:
    game_id="g1"


class Path:
    def __init__(self, rush, rec, active=True):
        self.base_path=Base()
        self.home_usage=Usage(Profile(active=active))
        self.away_usage=Usage(Profile("other", True))
        self._stats={"p1":{"rushing_tds":rush,"receiving_tds":rec}}
    def player_stats(self):
        return self._stats


def test_anytime_td_uses_at_least_one_rush_or_receiving_td():
    rows=[Path(0,0),Path(1,0),Path(0,1),Path(2,0)]
    assert derive_anytime_touchdown_probability(rows,player_id="p1")=={"yes":0.75,"no":0.25}


def test_anytime_td_does_not_count_passing_td():
    row=Path(0,0)
    row._stats["p1"]["passing_tds"]=4
    assert derive_anytime_touchdown_probability([row],player_id="p1")["yes"]==0.0


def test_two_plus_td_uses_same_shared_offensive_td_count():
    rows=[Path(0,0),Path(1,0),Path(1,1),Path(2,1)]
    assert derive_two_plus_touchdown_probability(rows,player_id="p1")=={"yes":0.5,"no":0.5}


def test_two_plus_td_does_not_count_passing_td():
    row=Path(1,0)
    row._stats["p1"]["passing_tds"]=5
    assert derive_two_plus_touchdown_probability([row],player_id="p1")["yes"]==0.0


def test_anytime_td_fails_closed_on_unresolved_participation():
    with pytest.raises(ValueError,match="PARTICIPATION_UNRESOLVED"):
        derive_anytime_touchdown_probability([Path(0,0,active=None)],player_id="p1")


def test_two_plus_td_fails_closed_on_unresolved_participation():
    with pytest.raises(ValueError,match="PARTICIPATION_UNRESOLVED"):
        derive_two_plus_touchdown_probability([Path(2,0,active=None)],player_id="p1")
