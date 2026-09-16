from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.mlb_moneyline_pit import MLBMoneylinePITError,build_moneyline_feature
def _rows(start):
 r=[]
 for team,base in ((10,3.),(20,4.)):
  for i in range(12):r.append({"team_id":team,"runs":base+(i%3),"feature_asof_ts":(start-timedelta(days=20-i)).isoformat(),"source_game_pk":f"{team}-{i}"})
 return r
def test_market_blind_strict_pit():
 s=datetime(2026,9,15,23,40,tzinfo=timezone.utc);o=build_moneyline_feature(game_pk=999,away_team_id=10,home_team_id=20,event_start_ts=s,observations=_rows(s),window=10,minimum=10)
 assert o["market_blind"] is True and datetime.fromisoformat(o["feature_asof_ts"])<s and "odds" in o["forbidden_market_inputs"]
def test_equal_timestamp_leaks():
 s=datetime(2026,9,15,23,40,tzinfo=timezone.utc);r=_rows(s);r.append({"team_id":10,"runs":99,"feature_asof_ts":s.isoformat(),"source_game_pk":"leak"})
 with pytest.raises(MLBMoneylinePITError,match="PIT_LEAKAGE"):build_moneyline_feature(game_pk=999,away_team_id=10,home_team_id=20,event_start_ts=s,observations=r,window=10,minimum=10)
def test_missing_timestamp_fails():
 s=datetime(2026,9,15,23,40,tzinfo=timezone.utc);r=_rows(s);r[0]={"team_id":10,"runs":3,"source_game_pk":"missing"}
 with pytest.raises(MLBMoneylinePITError,match="feature_asof_ts"):build_moneyline_feature(game_pk=999,away_team_id=10,home_team_id=20,event_start_ts=s,observations=r,window=10,minimum=10)
