import importlib.util
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_spec=importlib.util.spec_from_file_location(
    "settle_mlb_moneyline_forward_evidence",
    Path(__file__).resolve().parents[1]/"scripts"/"settle_mlb_moneyline_forward_evidence.py",
)
settle=importlib.util.module_from_spec(_spec); _spec.loader.exec_module(settle)

ART="a"*64
START="2026-09-16T18:00:00+00:00"
NOW=datetime(2026,9,16,22,0,0,tzinfo=timezone.utc)

def prediction():
    return {
        "status":"RETAINED",
        "game_pk":123,
        "away_team_id":2,
        "away_team":"Boston Red Sox",
        "home_team_id":1,
        "home_team":"New York Yankees",
        "model_side":"HOME",
        "model_p":0.55,
        "market_blind":True,
        "feature_asof_ts":"2026-09-16T17:00:00+00:00",
        "event_start_ts":START,
        "prediction_generated_at_utc":"2026-09-16T17:05:00+00:00",
        "model_artifact_sha256":ART,
    }

def quote(observed,home=-110,away=100,event_id="DK1"):
    return {
        "sportsbook":"draftkings",
        "provider_event_id":event_id,
        "home_team":"New York Yankees",
        "away_team":"Boston Red Sox",
        "scheduled_start_utc":START,
        "observed_at_utc":observed,
        "model_artifact_sha256":ART,
        "raw_sha256":"b"*64,
        "moneyline":{"status":"OK","home_price_american":home,"away_price_american":away},
    }

def final_source(away_id=2,home_id=1):
    raw=b'{"gamePk":123,"status":"Final"}'
    return {
        "settlement":{"game_pk":123,"status":"FINAL","away_team_id":away_id,"home_team_id":home_id,"away_score":3,"home_score":5},
        "source_uri":"https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk=123",
        "observed_at_utc":"2026-09-16T22:00:00+00:00",
        "raw_sha256":hashlib.sha256(raw).hexdigest(),
        "raw_bytes":raw,
    }

def write_json(path,row):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(row,sort_keys=True)+"\n",encoding="utf-8")

class SettlementWorkflowTest(unittest.TestCase):
    def roots(self,base):
        p=Path(base)
        return p/"pred",p/"quotes",p/"evidence",p/"raw",p/"report.json"

    def test_settles_complete_evidence_and_never_grants_authority(self):
        with tempfile.TemporaryDirectory() as d:
            pred,quotes,out,raw,report=self.roots(d)
            write_json(pred/"2026-09-16"/"game_123.json",prediction())
            write_json(quotes/"2026-09-16"/"decision.json",quote("2026-09-16T17:26:00+00:00",-110,100,"D"))
            write_json(quotes/"2026-09-16"/"close.json",quote("2026-09-16T17:58:00+00:00",-115,105,"C"))
            result=settle.settle_and_evaluate(
                prediction_root=pred,quote_root=quotes,output_root=out,raw_root=raw,report_path=report,
                now=NOW,settlement_fetcher=lambda game_pk:final_source(),
            )
            evidence=json.loads((out/"2026-09-16"/"game_123.json").read_text())
            raw_files=list(raw.rglob("*.json"))
        self.assertEqual(result["new_completed_evidence"],1)
        self.assertEqual(result["completed_evidence_total"],1)
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["deployment_change_allowed_by_this_report"])
        self.assertEqual(evidence["status"],"FORWARD_EVIDENCE_COMPLETE")
        self.assertEqual(evidence["decision_minutes_before_start"],34.0)
        self.assertEqual(evidence["close_minutes_before_start"],2.0)
        self.assertEqual(evidence["outcome"],1)
        self.assertEqual(len(raw_files),1)
        self.assertFalse(evidence["promotion_authority"])
        self.assertIn(ART,result["artifact_groups"])
        self.assertFalse(result["artifact_groups"][ART]["metric_prerequisites_pass"])

    def test_existing_complete_record_is_immutable_and_not_refetched(self):
        with tempfile.TemporaryDirectory() as d:
            pred,quotes,out,raw,report=self.roots(d)
            write_json(pred/"2026-09-16"/"game_123.json",prediction())
            write_json(quotes/"2026-09-16"/"decision.json",quote("2026-09-16T17:26:00+00:00"))
            write_json(quotes/"2026-09-16"/"close.json",quote("2026-09-16T17:58:00+00:00"))
            settle.settle_and_evaluate(prediction_root=pred,quote_root=quotes,output_root=out,raw_root=raw,report_path=report,now=NOW,settlement_fetcher=lambda game_pk:final_source())
            calls=[]
            result=settle.settle_and_evaluate(prediction_root=pred,quote_root=quotes,output_root=out,raw_root=raw,report_path=report,now=NOW,settlement_fetcher=lambda game_pk:calls.append(game_pk))
        self.assertEqual(calls,[])
        self.assertEqual(result["new_completed_evidence"],0)
        self.assertEqual(result["completed_evidence_total"],1)

    def test_nonfinal_remains_pending_without_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            pred,quotes,out,raw,report=self.roots(d)
            write_json(pred/"2026-09-16"/"game_123.json",prediction())
            result=settle.settle_and_evaluate(prediction_root=pred,quote_root=quotes,output_root=out,raw_root=raw,report_path=report,now=NOW,settlement_fetcher=lambda game_pk:None)
        self.assertEqual(result["pending_final_game_pks"],[123])
        self.assertEqual(result["completed_evidence_total"],0)
        self.assertFalse(result["promotion_authority"])

    def test_settlement_team_identity_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            pred,quotes,out,raw,report=self.roots(d)
            write_json(pred/"2026-09-16"/"game_123.json",prediction())
            with self.assertRaises(settle.MLBMoneylineSettlementError):
                settle.settle_and_evaluate(prediction_root=pred,quote_root=quotes,output_root=out,raw_root=raw,report_path=report,now=NOW,settlement_fetcher=lambda game_pk:final_source(away_id=99))

    def test_schedule_source_parser_requires_exact_final_identity(self):
        payload={"dates":[{"games":[{"gamePk":123,"status":{"abstractGameState":"Final"},"teams":{"away":{"team":{"id":2},"score":3},"home":{"team":{"id":1},"score":5}}}]}]}
        raw=json.dumps(payload).encode()
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): return False
            def read(self): return raw
        result=settle.fetch_final_settlement(123,opener=lambda *args,**kwargs:Response(),clock=lambda:NOW)
        self.assertEqual(result["settlement"]["home_score"],5)
        self.assertEqual(result["settlement"]["away_score"],3)
        self.assertEqual(result["raw_sha256"],hashlib.sha256(raw).hexdigest())

if __name__=="__main__": unittest.main()
