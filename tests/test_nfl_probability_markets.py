from __future__ import annotations

import numpy as np
import pytest

from sportsedge.core.simulate.nfl_probability_markets import (
    derive_anytime_touchdown_probability,
    derive_two_plus_touchdown_probability,
    derive_safety_probability,
)
from sportsedge.core.simulate.nfl_possession_challenger import VectorizedSummary


from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
from sportsedge.core.simulate.usage import (
    AttributedFootballPath, AttributedPlay, PlayerUsageProfile, TeamUsageProfile,
)


def Path(rush, rec, active=True, passing=0, game_id="g1"):
    """Real attributed plays exercise the public readout's type/identity contract."""
    home=TeamUsageProfile("H",(
        PlayerUsageProfile("p1","H","QB",active,1,1,.5,.5,.5),
        PlayerUsageProfile("other","H","WR",True,1,1,.5,.5,.5),
    ),"p1")
    away=TeamUsageProfile("A",(
        PlayerUsageProfile("away_qb","A","QB",True,1,0,0,1,1),
    ),"away_qb")
    plays=[]
    for i,kind in enumerate(["rush"]*rush+["rec"]*rec+["pass"]*passing,1):
        play=PlayEvent(
            drive_id=i,play_id=i,quarter=1,clock_seconds_remaining=900-i,
            possession="H",score_before_home=6*(i-1),score_before_away=0,
            score_after_home=6*i,score_after_away=0,down=1,distance=1,
            yardline_100=1,play_type="RUSH" if kind=="rush" else "PASS",
            yards=1,points=6,score_type="TOUCHDOWN_CANDIDATE",
            pass_complete=None if kind=="rush" else True,
        )
        if kind=="rush":
            attribution=dict(rusher_id="p1",touchdown_scorer_id="p1")
        else:
            receiver="p1" if kind=="rec" else "other"
            passer="other" if kind=="rec" else "p1"
            attribution=dict(passer_id=passer,target_id=receiver,
                             receiver_id=receiver,touchdown_scorer_id=receiver)
        plays.append(AttributedPlay(play,("p1","other"),**attribution))
    base=FootballPlayPath(game_id,0,"H","A",tuple(p.base_play for p in plays))
    return AttributedFootballPath(base,home,away,tuple(plays))


def test_anytime_td_uses_at_least_one_rush_or_receiving_td():
    rows=[Path(0,0),Path(1,0),Path(0,1),Path(2,0)]
    assert derive_anytime_touchdown_probability(rows,player_id="p1")=={"yes":0.75,"no":0.25}


def test_anytime_td_does_not_count_passing_td():
    row=Path(0,0,passing=4)
    assert derive_anytime_touchdown_probability([row],player_id="p1")["yes"]==0.0


def test_two_plus_td_uses_same_shared_offensive_td_count():
    rows=[Path(0,0),Path(1,0),Path(1,1),Path(2,1)]
    assert derive_two_plus_touchdown_probability(rows,player_id="p1")=={"yes":0.5,"no":0.5}


def test_two_plus_td_does_not_count_passing_td():
    row=Path(1,0,passing=5)
    assert derive_two_plus_touchdown_probability([row],player_id="p1")["yes"]==0.0


def test_safety_probability_uses_per_path_parent_outcome_counts():
    counts=np.zeros((4,7),dtype=np.int16)
    counts[1,5]=1
    counts[3,5]=2
    z=np.zeros(4,dtype=np.int16)
    summary=VectorizedSummary(z,z,z,z,counts,z)
    assert derive_safety_probability(summary)=={"yes":0.5,"no":0.5}


def test_safety_probability_fails_closed_without_paths():
    z=np.zeros(0,dtype=np.int16)
    summary=VectorizedSummary(z,z,z,z,np.zeros((0,7),dtype=np.int16),z)
    with pytest.raises(ValueError,match="SIMULATION_ROWS_EMPTY"):
        derive_safety_probability(summary)


def test_anytime_td_fails_closed_on_unresolved_participation():
    with pytest.raises(ValueError,match="PARTICIPATION_UNRESOLVED"):
        derive_anytime_touchdown_probability([Path(0,0,active=None)],player_id="p1")


def test_two_plus_td_fails_closed_on_unresolved_participation():
    with pytest.raises(ValueError,match="PARTICIPATION_UNRESOLVED"):
        derive_two_plus_touchdown_probability([Path(2,0,active=None)],player_id="p1")


@pytest.mark.parametrize("readout",[derive_anytime_touchdown_probability,derive_two_plus_touchdown_probability])
def test_td_readouts_reject_foreign_path_objects(readout):
    with pytest.raises(TypeError,match="ATTRIBUTED_FOOTBALL_PATH_REQUIRED"):
        readout([object()],player_id="p1")


@pytest.mark.parametrize("readout",[derive_anytime_touchdown_probability,derive_two_plus_touchdown_probability])
def test_td_readouts_reject_mixed_games_and_inactive_players(readout):
    with pytest.raises(ValueError,match="PLAYER_MARKET_GAME_ID_MISMATCH"):
        readout([Path(1,0),Path(0,1,game_id="g2")],player_id="p1")
    with pytest.raises(ValueError,match="PLAYER_INACTIVE"):
        readout([Path(0,0,active=False)],player_id="p1")


@pytest.mark.parametrize("bad",[float("nan"),float("inf"),-1,.5,True,"1",None])
@pytest.mark.parametrize("component",["rushing_tds","receiving_tds"])
@pytest.mark.parametrize("readout",[derive_anytime_touchdown_probability,derive_two_plus_touchdown_probability])
def test_td_readouts_reject_corrupt_counts(monkeypatch,bad,component,readout):
    row={"rushing_tds":1,"receiving_tds":1}
    row[component]=bad
    monkeypatch.setattr(AttributedFootballPath,"player_stats",lambda self:{"p1":row})
    with pytest.raises(ValueError,match="PLAYER_TD_COUNT_INVALID"):
        readout([Path(0,0)],player_id="p1")


@pytest.mark.parametrize("bad",[float("nan"),float("inf"),-1,.5])
@pytest.mark.parametrize("column",[0,5])
def test_safety_readout_rejects_corrupt_outcome_counts(bad,column):
    counts=np.zeros((2,7),dtype=float)
    counts[0,column]=bad
    z=np.zeros(2,dtype=int)
    with pytest.raises(ValueError,match="CHALLENGER_OUTCOME_COUNT_INVALID"):
        derive_safety_probability(VectorizedSummary(z,z,z,z,counts,z))


def test_safety_readout_rejects_mismatched_parent_rows():
    z=np.zeros(2,dtype=int)
    summary=VectorizedSummary(z,z,z,z,np.zeros((3,7),dtype=int),z)
    with pytest.raises(ValueError,match="CHALLENGER_SUMMARY_ROW_MISMATCH"):
        derive_safety_probability(summary)
