import gzip,hashlib,pytest
from sportsedge.sports.cfb.sportsdataverse_csv import *

def _parse(s,d="cfb_schedules"):
 raw=s.encode(); return parse_csv(raw,dataset=d,season=2025,source_url="https://example.test/x.csv",raw_csv_sha256=hashlib.sha256(raw).hexdigest())

def test_bom_and_required_schedule_columns():
 rows,r=_parse("\ufeffgame_id,season,week,season_type,fbs_game,home_id,away_id,home_points,away_points\n1,2025,1,2,true,10,20,21,14\n")
 assert rows[0]["game_id"]=="1" and r.row_count==1

def test_duplicate_header_fails():
 with pytest.raises(SDVCSVError,match="DUPLICATE_HEADER"): _parse("game_id,season,week,season_type,fbs_game,game_id\n1,2025,1,2,true,1\n")

def test_market_column_fails():
 with pytest.raises(SDVCSVError,match="MARKET_COLUMN_PROHIBITED"): _parse("game_id,season,week,season_type,fbs_game,home_id,away_id,home_points,away_points,spread\n1,2025,1,2,true,10,20,21,14,-3\n")

def test_wrong_season_fails():
 with pytest.raises(SDVCSVError,match="SEASON_MISMATCH"): _parse("game_id,season,week,season_type,fbs_game,home_id,away_id,home_points,away_points\n1,2024,1,2,true,10,20,21,14\n")


def test_schedule_requires_game_identity_and_labels():
    raw=b"game_id,season,week,season_type,fbs_game\n1,2025,1,2,true\n"
    import hashlib
    try:
        parse_csv(raw,dataset="cfb_schedules",season=2025,source_url="x",raw_csv_sha256=hashlib.sha256(raw).hexdigest())
    except SDVCSVError as e:
        assert "CFB_SDV_CSV_REQUIRED_COLUMNS_MISSING" in str(e)
        assert "home_id" in str(e)
    else:
        raise AssertionError("expected fail closed")


def test_raw_hash_mismatch_fails_closed():
    raw=b"game_id,season,week,season_type,fbs_game,home_id,away_id,home_points,away_points\n1,2025,1,2,true,10,20,21,14\n"
    try:
        parse_csv(raw,dataset="cfb_schedules",season=2025,source_url="x",raw_csv_sha256="0"*64)
    except SDVCSVError as e:
        assert str(e)=="CFB_SDV_CSV_RAW_HASH_MISMATCH"
    else:
        raise AssertionError("expected raw hash mismatch")


def test_schedule_gzip_transport_hashes_compressed_bytes_then_parses_csv():
 raw_csv=b"game_id,season,week,season_type,fbs_game,home_id,away_id,home_points,away_points\n1,2025,1,2,true,10,20,21,14\n"
 raw=gzip.compress(raw_csv,mtime=0)
 rows,r=parse_csv(
  raw,
  dataset="cfb_schedules",
  season=2025,
  source_url="https://example.test/cfb_schedules_2025.csv.gz",
  raw_csv_sha256=hashlib.sha256(raw).hexdigest(),
 )
 assert rows[0]["game_id"]=="1"
 assert r.raw_csv_sha256==hashlib.sha256(raw).hexdigest()


def test_invalid_gzip_transport_fails_closed():
 raw=b"not-gzip"
 with pytest.raises(SDVCSVError,match="CFB_SDV_CSV_GZIP_INVALID"):
  parse_csv(
   raw,
   dataset="cfb_schedules",
   season=2025,
   source_url="https://example.test/cfb_schedules_2025.csv.gz",
   raw_csv_sha256=hashlib.sha256(raw).hexdigest(),
  )
