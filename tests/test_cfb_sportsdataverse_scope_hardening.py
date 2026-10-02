import pytest
from sportsedge.sports.cfb.sportsdataverse_history import (
 SportsDataverseHistoryError,regular_fbs_schedule_rows,build_team_snapshots
)

def test_malformed_fbs_flag_fails_closed():
 with pytest.raises(SportsDataverseHistoryError,match="FBS_GAME_FLAG_INVALID"):
  regular_fbs_schedule_rows([{"game_id":1,"season":2025,"week":1,"season_type":2,"fbs_game":"maybe"}])

def test_known_non_fbs_game_is_excluded():
 assert regular_fbs_schedule_rows([{"game_id":1,"season":2025,"week":1,"season_type":2,"fbs_game":False}]) == []

def test_advanced_game_without_schedule_fails_closed():
 team={"game_id":99,"season":2025,"week":1,"pos_team":1}
 with pytest.raises(SportsDataverseHistoryError,match="ADV_GAME_MISSING_SCHEDULE"):
  build_team_snapshots(adv_team_rows=[team],adv_situational_rows=[],adv_drive_rows=[],
   schedule_rows=[{"game_id":1,"season":2025,"week":1,"season_type":2,"fbs_game":True}],
   target_season=2025,target_week=2)
