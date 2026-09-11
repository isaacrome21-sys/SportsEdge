import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.card_pipeline import run_hitter_card
from sportsedge.hits_engine import FEATURE_CONTRACT_VERSION as HITS_FEATURE_VERSION
from sportsedge.total_bases_engine import FEATURE_CONTRACT_VERSION as TB_FEATURE_VERSION
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot

UTC=timezone.utc; NOW=datetime(2026,8,10,20,0,tzinfo=UTC)
def rows(start): return [{"player_id":start+i,"slot":i+1,"sequence":0} for i in range(9)]
def game():
    s=GameSnapshot(game_pk=777,game_date="2026-08-10T23:00:00Z",status="Preview",away_id=1,away_name="Away",home_id=2,home_name="Home",away_probable_pitcher_id=11,away_probable_pitcher_name="A",home_probable_pitcher_id=22,home_probable_pitcher_name="H",retrieved_at="2026-08-10T19:59:00+00:00")
    return make_live_game(s,rows(100),rows(200))
def feature(pid=100): return {"game_pk":777,"player_id":pid,"team_id":1,"market":"HITS","feature_version":HITS_FEATURE_VERSION,"b_rate":.60,"p_rate":.60,"pa_pool":[4,5,4,5]}
def tb_feature(pid=100): return {"game_pk":777,"player_id":pid,"team_id":1,"market":"TOTAL_BASES","feature_version":TB_FEATURE_VERSION,"rates":{"s":.20,"d":.08,"t":.01,"hr":.08},"p_h":.35,"p_hr":.06,"park":1.20,"pa_pool":[4,5,4,5]}
def quote(pid=100,market="HITS",side="OVER",odds=100): return {"game_id":"777","period":"FG","market":market,"entity_id":str(pid),"line":.5,"side":side,"book_key":"draftkings","is_alternate":False,"raw_market_name":"Player Hits" if market=="HITS" else "Player Total Bases","american_odds":odds,"retrieved_at":NOW,"ttl_seconds":300}
def pair(market="HITS"): return [quote(market=market,side="OVER",odds=100),quote(market=market,side="UNDER",odds=-120)]
def deployed_registry(path,deploy_tb=False): path.write_text(json.dumps({"schema_version":1,"markets":{"HITS":{"eligible":True,"stage":"DEPLOYED","reason":"test"},"TOTAL_BASES":{"eligible":bool(deploy_tb),"stage":"DEPLOYED" if deploy_tb else "PRODUCTION_LOGIC_PASS","reason":"test"}}}))
def floor_registry(path,markets):
    record={"status":"FROZEN","value_probability_points":0.01,"method_version":"test_fixture_v1","evidence":{"evidence_sha256":"e"*64,"derivation_code_sha256":"d"*64,"oos_cutoff_utc":"2026-08-01T00:00:00Z"},"frozen":{"frozen_by_commit":"a"*40}}
    devig={"policy_id":"EDGE_FLOOR_DEVIG_V1","status":"FROZEN_PRE_DERIVATION","longshot_trigger_american_odds":400,"longshot_trigger_rule":"EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400","sensitivity_methods":["MULTIPLICATIVE_V1","POWER_V1","SHIN_V1"],"sensitivity_limit_absolute_probability_points":0.01,"stable_candidate_estimator":"MULTIPLICATIVE_V1","longshot_candidate_estimator":"POWER_V1","haircut_probability_points":0.0,"aggregation_rule":"ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS","sensitivity_failure":"BLOCK"}
    path.write_text(json.dumps({"truth_gate":{"schema_version":2,"production":{"fail_closed":True,"allow_cli_floor_override":False,"require_frozen_floor_for_eligible_market":True},"devig_policy":devig,"edge_floors":{m:dict(record) for m in markets}}}))

class CardPipelineTests(unittest.TestCase):
    def test_checked_in_registry_keeps_hits_blocked(self):
        out=run_hitter_card(games=[game()],feature_rows=[feature()],quotes=[quote()],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED")
    def test_deployed_hits_cannot_promote_legacy_compat_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"d.json"; f=Path(td)/"floors.json"; deployed_registry(p); floor_registry(f,["HITS"])
            out=run_hitter_card(games=[game()],feature_rows=[feature()],quotes=pair(),ingestion_now=NOW,finalization_now=NOW,registry_path=str(p),edge_floor_config_path=str(f))
        self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIsNone(out[0].model_p); self.assertIn("LEGACY_COMPAT_PATH_NOT_CANDIDATE",out[0].reason)
    def test_deployed_tb_cannot_promote_legacy_compat_payload(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"d.json"; f=Path(td)/"floors.json"; deployed_registry(p,True); floor_registry(f,["TOTAL_BASES"])
            out=run_hitter_card(games=[game()],feature_rows=[tb_feature()],quotes=pair("TOTAL_BASES"),ingestion_now=NOW,finalization_now=NOW,registry_path=str(p),edge_floor_config_path=str(f))
        self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIsNone(out[0].model_p); self.assertIn("LEGACY_COMPAT_PATH_NOT_CANDIDATE",out[0].reason)
    def test_hits_and_tb_can_coexist(self):
        out=run_hitter_card(games=[game()],feature_rows=[feature(),tb_feature()],quotes=[quote(),quote(market="TOTAL_BASES")],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(len(out),2)
    def test_direct_quote_missing_taxonomy_blocks(self):
        q=quote(); del q["book_key"]; out=run_hitter_card(games=[game()],feature_rows=[feature()],quotes=[q],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIn("QUOTE_IDENTITY_INCOMPLETE",out[0].reason)
    def test_unversioned_live_feature_blocks(self):
        f=feature(); del f["feature_version"]; out=run_hitter_card(games=[game()],feature_rows=[f],quotes=[quote()],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIn("feature contract mismatch",out[0].reason)
    def test_missing_feature_preserved(self):
        out=run_hitter_card(games=[game()],feature_rows=[],quotes=[quote()],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIn("feature snapshot missing",out[0].reason)
    def test_wrong_market_feature_does_not_cross_feed(self):
        out=run_hitter_card(games=[game()],feature_rows=[feature()],quotes=[quote(market="TOTAL_BASES")],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED")
    def test_stale_price_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"d.json"; deployed_registry(p); q=quote(); q["ttl_seconds"]=10; out=run_hitter_card(games=[game()],feature_rows=[feature()],quotes=[q],ingestion_now=NOW,finalization_now=NOW.replace(minute=1),registry_path=str(p))
        self.assertEqual(out[0].bet_status,"BLOCKED")
    def test_duplicate_quote_preserved_as_blocked(self):
        q=quote(); out=run_hitter_card(games=[game()],feature_rows=[feature()],quotes=[q,dict(q)],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(len(out),2); self.assertEqual(out[1].bet_status,"BLOCKED")

if __name__=="__main__": unittest.main()
