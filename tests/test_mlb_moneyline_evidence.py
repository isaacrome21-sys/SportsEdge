from datetime import datetime,timedelta,timezone
import pytest
from sportsedge.mlb_moneyline_evidence import MLBMoneylineEvidenceError,evaluate_moneyline_predictions
def _rows(n=200):
 s=datetime(2026,4,1,23,tzinfo=timezone.utc);return [{"model_p":.35+(i%30)/100,"outcome":1 if (i*17)%100<int((.35+(i%30)/100)*100) else 0,"market_blind":True,"feature_asof_ts":(s-timedelta(hours=1)).isoformat(),"event_start_ts":s.isoformat()} for i in range(n)]
def test_empty_blocked():assert evaluate_moneyline_predictions([])["promotion_authority"] is False
def test_metrics_and_sample():
 o=evaluate_moneyline_predictions(_rows());assert o["n"]==200 and o["sample_gate_pass"] is True and o["promotion_authority"] is False
 for k in ("brier","log_loss","calibration_slope","calibration_intercept","ece"):assert k in o
def test_under_200_blocked():assert evaluate_moneyline_predictions(_rows(199))["sample_gate_pass"] is False
def test_market_blind_required():
 r=_rows();r[0]["market_blind"]=False
 with pytest.raises(MLBMoneylineEvidenceError,match="market_blind"):evaluate_moneyline_predictions(r)
def test_equal_asof_leaks():
 r=_rows();r[0]["feature_asof_ts"]=r[0]["event_start_ts"]
 with pytest.raises(MLBMoneylineEvidenceError,match="PIT_LEAKAGE"):evaluate_moneyline_predictions(r)
