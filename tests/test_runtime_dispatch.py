import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.engine_registry import EngineDispatchError, hits_engine_adapter
from sportsedge.runtime import RuntimeInputError, result_to_dict, run_payload


def legacy_model_input(side="OVER", line=0.5):
    return {"build_hash":"a"*64,"game_id":"game-1","market":"HITS","entity_id":"batter-1","line":line,"side":side,"lineup_status":"CONFIRMED","require_confirmed_lineup":True,"features":{"b_rate":0.31,"p_rate":0.27,"pa_pool":[3,4,4,4,5]}}

def joint_row(hits):
    return {"plate_appearances":4,"hits":hits,"singles":hits,"doubles":0,"triples":0,"home_runs":0,"total_bases":hits,"rbi":0,"runs":0,"stolen_bases":0,"walks":0,"strikeouts":1,"extra_base_hits":0}

def model_input(side="OVER", line=0.5):
    return {"game_id":"game-1","market":"HITS","entity_id":"batter-1","line":line,"side":side,"feature_source_hash":"a"*64,"features":{"history_pool":[joint_row(1) for _ in range(7)]+[joint_row(0) for _ in range(3)]}}

def quote(*,side="OVER",line=0.5,odds=100,retrieved="2026-08-10T20:00:00Z",ttl=300):
    return {"game_id":"game-1","market":"HITS","entity_id":"batter-1","line":line,"side":side,"american_odds":odds,"retrieved_at":retrieved,"ttl_seconds":ttl,"book_key":"draftkings"}

def payload(q=None,mi=None):
    candidate_quote=q or quote()
    pair_quote=quote(side="UNDER",line=candidate_quote.get("line",0.5),odds=-120,retrieved=candidate_quote.get("retrieved_at","2026-08-10T20:00:00Z"),ttl=candidate_quote.get("ttl_seconds",300))
    return {"ingestion_now":"2026-08-10T20:01:00Z","finalization_now":"2026-08-10T20:01:10Z","kelly_multiplier":0.25,"candidates":[{"model_input":mi or model_input(),"quote":candidate_quote,"paired_quote":pair_quote}]}

def registry(path:Path,*,eligible:bool,stage:str): path.write_text(json.dumps({"schema_version":1,"markets":{"HITS":{"eligible":eligible,"stage":stage,"reason":"test"}}}),encoding="utf-8")
def floors(path:Path):
    devig={"policy_id":"EDGE_FLOOR_DEVIG_V1","status":"FROZEN_PRE_DERIVATION","longshot_trigger_american_odds":400,"longshot_trigger_rule":"EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400","sensitivity_methods":["MULTIPLICATIVE_V1","POWER_V1","SHIN_V1"],"sensitivity_limit_absolute_probability_points":0.01,"stable_candidate_estimator":"MULTIPLICATIVE_V1","longshot_candidate_estimator":"POWER_V1","haircut_probability_points":0.0,"aggregation_rule":"ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS","sensitivity_failure":"BLOCK"}
    path.write_text(json.dumps({"truth_gate":{"schema_version":2,"production":{"fail_closed":True,"allow_cli_floor_override":False,"require_frozen_floor_for_eligible_market":True},"devig_policy":devig,"edge_floors":{"HITS":{"status":"FROZEN","value_probability_points":0.01,"method_version":"test_fixture_v1","evidence":{"evidence_sha256":"e"*64,"derivation_code_sha256":"d"*64,"oos_cutoff_utc":"2026-08-01T00:00:00Z"},"frozen":{"frozen_by_commit":"a"*40}}}}}),encoding="utf-8")

class RuntimeDispatchTests(unittest.TestCase):
    def test_hits_adapter_is_deterministic_and_common_schema(self):
        a=hits_engine_adapter(legacy_model_input()); b=hits_engine_adapter(legacy_model_input()); self.assertEqual(a,b); self.assertEqual(a["market"],"HITS"); self.assertEqual(a["game_id"],"game-1"); self.assertTrue(0<=a["model_p"]<=1)
    def test_hits_under_is_complement_of_same_over_paths(self):
        self.assertAlmostEqual(hits_engine_adapter(legacy_model_input("OVER"))["model_p"]+hits_engine_adapter(legacy_model_input("UNDER"))["model_p"],1.0,places=12)
    def test_unsupported_hits_line_rejected(self):
        with self.assertRaises(EngineDispatchError): hits_engine_adapter(legacy_model_input(line=3.5))
    def test_checked_in_registry_retains_model_candidate_but_not_official(self):
        result=run_payload(payload())[0]
        self.assertEqual(result.bet_status,"MODEL_CANDIDATE")
        self.assertIsNotNone(result.model_p)
        self.assertIn("OFFICIAL_BLOCKED",result.reason)
        self.assertIn("eligible",result.reason.lower())
    def test_deployed_test_registry_can_reach_truth_gate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"registry.json"; f=Path(td)/"floors.json"; registry(p,eligible=True,stage="DEPLOYED"); floors(f); result=run_payload(payload(),registry_path=p,edge_floor_config_path=str(f))[0]
            self.assertIn(result.bet_status,("OFFICIAL_BET","PASS")); self.assertIsNotNone(result.model_p); doc=result_to_dict(result); self.assertIn("implied_probability",doc["decision"]); self.assertIn("ev_per_dollar",doc["decision"])
    def test_quote_timestamp_string_is_parsed_and_double_ttl_blocks_final_stale(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"registry.json"; f=Path(td)/"floors.json"; registry(p,eligible=True,stage="DEPLOYED"); floors(f); x=payload(q=quote(retrieved="2026-08-10T19:56:30Z",ttl=300)); x["ingestion_now"]="2026-08-10T20:01:00Z"; x["finalization_now"]="2026-08-10T20:01:40Z"; result=run_payload(x,registry_path=p,edge_floor_config_path=str(f))[0]
            self.assertEqual(result.bet_status,"BLOCKED"); self.assertIn("price is stale",result.reason)
    def test_candidate_binding_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"registry.json"; f=Path(td)/"floors.json"; registry(p,eligible=True,stage="DEPLOYED"); floors(f); q=quote(); q["entity_id"]="wrong-batter"; result=run_payload(payload(q=q),registry_path=p,edge_floor_config_path=str(f))[0]
            self.assertEqual(result.bet_status,"BLOCKED"); self.assertIn("candidate mismatch: entity_id",result.reason)
    def test_naive_pipeline_timestamp_rejected_before_run(self):
        x=payload(); x["ingestion_now"]="2026-08-10T20:01:00"
        with self.assertRaises(RuntimeInputError): run_payload(x)
    def test_runtime_floor_overrides_are_prohibited(self):
        for field,value in (("min_edge",0.0),("edge_floor",0.01),("edge_floor_config","other.json"),("edge_floor_config_path","other.json")):
            x=payload(); x[field]=value
            with self.subTest(field=field):
                with self.assertRaises(RuntimeInputError): run_payload(x)
    def test_invalid_kelly_controls_fail_closed(self):
        for value in (1.1,True,float("nan")):
            x=payload(); x["kelly_multiplier"]=value
            with self.subTest(value=value):
                with self.assertRaises(RuntimeInputError): run_payload(x)

if __name__=="__main__": unittest.main()
