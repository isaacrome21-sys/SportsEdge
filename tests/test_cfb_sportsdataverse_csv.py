import hashlib,pytest
from sportsedge.sports.cfb.sportsdataverse_csv import *

def _parse(s,d="cfb_schedules"):
 raw=s.encode(); return parse_csv(raw,dataset=d,season=2025,source_url="https://example.test/x.csv",raw_csv_sha256=hashlib.sha256(raw).hexdigest())

def test_bom_and_required_schedule_columns():
 rows,r=_parse("\ufeffgame_id,season,week,season_type,fbs_game\n1,2025,1,2,true\n")
 assert rows[0]["game_id"]=="1" and r.row_count==1

def test_duplicate_header_fails():
 with pytest.raises(SDVCSVError,match="DUPLICATE_HEADER"): _parse("game_id,season,week,season_type,fbs_game,game_id\n1,2025,1,2,true,1\n")

def test_market_column_fails():
 with pytest.raises(SDVCSVError,match="MARKET_COLUMN_PROHIBITED"): _parse("game_id,season,week,season_type,fbs_game,spread\n1,2025,1,2,true,-3\n")

def test_wrong_season_fails():
 with pytest.raises(SDVCSVError,match="SEASON_MISMATCH"): _parse("game_id,season,week,season_type,fbs_game\n1,2024,1,2,true\n")
