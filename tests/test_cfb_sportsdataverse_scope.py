import pytest
from sportsedge.sports.cfb.sportsdataverse_history import regular_fbs_schedule_rows,SportsDataverseHistoryError

def test_regular_fbs_scope_keeps_only_regular_fbs_vs_fbs():
 rows=[
  {"season":2025,"game_id":1,"season_type":"regular","home_id":10,"away_id":20},
  {"season":2025,"game_id":2,"season_type":"postseason","home_id":10,"away_id":20},
  {"season":2025,"game_id":3,"season_type":"regular","home_id":10,"away_id":99},
 ]
 assert [r["game_id"] for r in regular_fbs_schedule_rows(rows,fbs_team_ids=[10,20])]==[1]

def test_scope_gate_requires_explicit_fbs_membership():
 with pytest.raises(SportsDataverseHistoryError,match="FBS_ALLOWLIST_REQUIRED"):
  regular_fbs_schedule_rows([{"season":2025,"game_id":1,"season_type":"regular","home_id":10,"away_id":20}],fbs_team_ids=[])

def test_scope_gate_requires_season_type():
 with pytest.raises(SportsDataverseHistoryError,match="SEASON_TYPE_REQUIRED"):
  regular_fbs_schedule_rows([{"season":2025,"game_id":1,"home_id":10,"away_id":20}],fbs_team_ids=[10,20])
