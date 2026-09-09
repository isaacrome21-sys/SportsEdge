import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.identity_rng import build_hash, candidate_rng, validate_build_hash, IdentityError
from sportsedge.candidate_binding import bind_candidate, BindingError
from sportsedge.price_ttl import double_ttl_gate, PriceFreshnessError
from sportsedge.truth_gate import decide_bet, TruthGateError
from sportsedge.orchestrator import run_candidate


DEVIG_POLICY = {
    "policy_id": "EDGE_FLOOR_DEVIG_V1",
    "status": "FROZEN_PRE_DERIVATION",
    "longshot_trigger_american_odds": 400,
    "longshot_trigger_rule": "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400",
    "sensitivity_methods": ["MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"],
    "sensitivity_limit_absolute_probability_points": 0.01,
    "stable_candidate_estimator": "MULTIPLICATIVE_V1",
    "longshot_candidate_estimator": "POWER_V1",
    "haircut_probability_points": 0.0,
    "aggregation_rule": "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS",
    "sensitivity_failure": "BLOCK",
}


class AutomationCoreTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
        self.key = {"game_id":"g1","market":"HITS","entity_id":"p1","line":"0.5","side":"OVER"}
        self.quote = dict(self.key, american_odds=120, retrieved_at=self.now-timedelta(seconds=10), ttl_seconds=300, book_key="draftkings")
        self.paired_quote = dict(self.quote, side="UNDER", american_odds=-130)
        self.deploy = {"market":"HITS","eligible":True}
        self.tmp = tempfile.TemporaryDirectory()
        self.floor_path = str(Path(self.tmp.name) / "floors.json")
        Path(self.floor_path).write_text(json.dumps({
            "truth_gate": {"schema_version": 2,
            "production": {"fail_closed": True,"allow_cli_floor_override": False,"require_frozen_floor_for_eligible_market": True},
            "devig_policy": DEVIG_POLICY,
            "edge_floors": {"HITS": {"status": "FROZEN","value_probability_points": 0.01,"method_version": "test_fixture_v1",
            "evidence": {"evidence_sha256": "e" * 64,"derivation_code_sha256": "d" * 64,"oos_cutoff_utc": "2026-08-01T00:00:00Z"},
            "frozen": {"frozen_by_commit": "a" * 40}}}}
        }), encoding="utf-8")

    def tearDown(self): self.tmp.cleanup()

    def test_rng_reproducible_and_identity_specific(self):
        a=build_hash(["g1","HITS","p1","0.5","OVER"]); b=build_hash(["g1","HITS","p2","0.5","OVER"])
        self.assertEqual(candidate_rng(a).random(),candidate_rng(a).random()); self.assertNotEqual(candidate_rng(a).random(),candidate_rng(b).random())

    def test_hash_requires_exact_sha256_hex(self):
        for bad in ("g"*64,"a"*63,"a"*65,""):
            with self.assertRaises(IdentityError): validate_build_hash(bad)

    def test_binding_rejects_wrong_line_and_truthy_attestation(self):
        model=dict(self.key,model_p=.60); badq=dict(self.quote,line="1.5")
        with self.assertRaises(BindingError): bind_candidate(model,badq,self.deploy)
        with self.assertRaises(BindingError): bind_candidate(model,self.quote,{"market":"HITS","eligible":1})

    def test_double_ttl_fresh_then_stale(self):
        with self.assertRaises(PriceFreshnessError): double_ttl_gate(dict(self.quote,retrieved_at=self.now-timedelta(seconds=280)),self.now,self.now+timedelta(seconds=30))

    def test_ttl_rejects_nonfinite(self):
        for ttl in (float("inf"),float("nan"),0,-1):
            with self.assertRaises(PriceFreshnessError): double_ttl_gate(dict(self.quote,ttl_seconds=ttl),self.now,self.now)

    def test_truth_gate_official_pass_blocked(self):
        self.assertEqual(decide_bet(.60,120,fair_market_probability=.48,bound=True,fresh=True,deployed=True,edge_floor=.01).bet_status,"OFFICIAL_BET")
        self.assertEqual(decide_bet(.40,120,fair_market_probability=.48,bound=True,fresh=True,deployed=True,edge_floor=.01).bet_status,"PASS")
        self.assertEqual(decide_bet(.60,120,fair_market_probability=.48,bound=False,fresh=True,deployed=True,edge_floor=.01).bet_status,"BLOCKED")

    def test_truth_gate_rejects_invalid_odds_and_floor(self):
        for odds in (0,99,-99,float("inf"),float("nan")):
            with self.assertRaises(TruthGateError): decide_bet(.6,odds,fair_market_probability=.48,bound=True,fresh=True,deployed=True,edge_floor=.01)
        for floor in (0,-.01,float("inf"),float("nan")):
            with self.assertRaises(TruthGateError): decide_bet(.6,120,fair_market_probability=.48,bound=True,fresh=True,deployed=True,edge_floor=floor)

    def test_end_to_end_blocks_price_leakage(self):
        result=run_candidate(model_input=dict(self.key,build_hash="a"*64,sportsbook_probability=.5),quote=self.quote,paired_quote=self.paired_quote,deployment=self.deploy,engine_fn=lambda x:dict(self.key,model_p=.6),ingestion_now=self.now,finalization_now=self.now,edge_floor_config_path=self.floor_path)
        self.assertEqual(result.bet_status,"BLOCKED"); self.assertIn("prohibited",result.reason)

    def test_end_to_end_valid_and_stale(self):
        mi=dict(self.key,build_hash="a"*64); engine=lambda x:dict(self.key,model_p=.60)
        result=run_candidate(model_input=mi,quote=self.quote,paired_quote=self.paired_quote,deployment=self.deploy,engine_fn=engine,ingestion_now=self.now,finalization_now=self.now,edge_floor_config_path=self.floor_path)
        self.assertEqual(result.bet_status,"OFFICIAL_BET")
        stale=dict(self.quote,retrieved_at=self.now-timedelta(seconds=301))
        result2=run_candidate(model_input=mi,quote=stale,paired_quote=self.paired_quote,deployment=self.deploy,engine_fn=engine,ingestion_now=self.now,finalization_now=self.now,edge_floor_config_path=self.floor_path)
        self.assertEqual(result2.bet_status,"BLOCKED")

    def test_floor_policy_precedes_engine_and_legacy_in_production(self):
        cfg = json.loads(Path(self.floor_path).read_text())
        cfg["truth_gate"]["production"]["require_frozen_floor_for_eligible_market"] = False
        Path(self.floor_path).write_text(json.dumps(cfg))
        calls = []
        def engine(_):
            calls.append(True)
            return dict(self.key, runtime_path="LEGACY_COMPAT")
        result = run_candidate(model_input=dict(self.key, build_hash="a"*64),
            quote=self.quote, paired_quote=self.paired_quote, deployment=self.deploy,
            engine_fn=engine, ingestion_now=self.now, finalization_now=self.now,
            edge_floor_config_path=self.floor_path)
        self.assertEqual(result.reason, "EdgeFloorError: FROZEN_FLOOR_POLICY_REQUIRED")
        self.assertEqual(calls, [])

    def test_missing_floor_fails_closed(self):
        missing=str(Path(self.tmp.name)/"missing.json")
        result=run_candidate(model_input=dict(self.key,build_hash="a"*64),quote=self.quote,paired_quote=self.paired_quote,deployment=self.deploy,engine_fn=lambda x:dict(self.key,model_p=.60),ingestion_now=self.now,finalization_now=self.now,edge_floor_config_path=missing)
        self.assertEqual(result.bet_status,"BLOCKED"); self.assertIn("EdgeFloorError",result.reason)


if __name__ == "__main__": unittest.main()
