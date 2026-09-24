from sportsedge.core.simulate.football_path import FootballGamePath,ScoringEvent
from sportsedge.core.simulate.markets import derive_sequence_markets

def _p(i,events):
 return FootballGamePath(game_id="g",simulation_id=i,home_team="H",away_team="A",events=tuple(events))

def _e(i,team,pts=7,clock=800):
 return ScoringEvent(event_id=str(i),period=1,clock_seconds_remaining=clock,team=team,points=pts,score_type="TD_PLUS_TRY_CANDIDATE")

def test_sequence_markets_use_ordered_parent_path():
 paths=[_p(1,[_e(1,"H")]),_p(2,[_e(2,"A",3)]),_p(3,[])]
 x=derive_sequence_markets(paths,race_points=[3])
 assert x["first_score"]=={"H":1/3,"A":1/3,"none":1/3}
 assert x["race_to_n_points"][3]=={"H":1/3,"A":1/3,"none":1/3}
