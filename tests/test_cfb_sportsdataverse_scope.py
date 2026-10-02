import pytest
from sportsedge.sports.cfb.sportsdataverse_history import regular_fbs_schedule_rows,SportsDataverseHistoryError

def test_regular_fbs_scope_keeps_only_upstream_regular_fbs_games():
 rows=[
  {"season":2025,"game_id":1,"season_type":"regular","fbs_game":True},
  {"season":2025,"game_id":2,"season_type":"postseason","fbs_game":True},
  {"season":2025,"game_id":3,"season_type":"regular","fbs_game":False},
 ]
 assert [r["game_id"] for r in regular_fbs_schedule_rows(rows)]==[1]

def test_scope_gate_requires_explicit_fbs_game_flag():
 with pytest.raises(SportsDataverseHistoryError,match="FBS_GAME_FLAG_REQUIRED"):
  regular_fbs_schedule_rows([{"season":2025,"game_id":1,"season_type":"regular"}])

def test_scope_gate_requires_season_type():
 with pytest.raises(SportsDataverseHistoryError,match="SEASON_TYPE_REQUIRED"):
  regular_fbs_schedule_rows([{"season":2025,"game_id":1,"fbs_game":True}])
