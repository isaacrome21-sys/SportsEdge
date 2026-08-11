import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.identity_rng import build_hash, candidate_rng, validate_build_hash, IdentityError
from sportsedge.candidate_binding import bind_candidate, BindingError
from sportsedge.price_ttl import double_ttl_gate, PriceFreshnessError
from sportsedge.truth_gate import decide_bet, TruthGateError
from sportsedge.orchestrator import run_candidate


class AutomationCoreTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
        self.key = {"game_id":"g1","market":"HITS","entity_id":"p1","line":"0.5","side":"OVER"}
        self.quote = dict(self.key, american_odds=120, retrieved_at=self.now-timedelta(seconds=10), ttl_seconds=300)
        self.deploy = {"market":"HITS","eligible":True}

    def test_rng_reproducible_and_identity_specific(self):
        a = build_hash(["g1","HITS","p1","0.5","OVER"])
        b = build_hash(["g1","HITS","p2","0.5","OVER"])
        self.assertEqual(candidate_rng(a).random(), candidate_rng(a).random())
        self.assertNotEqual(candidate_rng(a).random(), candidate_rng(b).random())

    def test_hash_requires_exact_sha256_hex(self):
        for bad in ("g"*64, "a"*63, "a"*65, ""):
            with self.assertRaises(IdentityError): validate_build_hash(bad)

    def test_binding_rejects_wrong_line_and_truthy_attestation(self):
        model = dict(self.key, model_p=.60)
        badq = dict(self.quote, line="1.5")
        with self.assertRaises(BindingError): bind_candidate(model, badq, self.deploy)
        with self.assertRaises(BindingError): bind_candidate(model, self.quote, {"market":"HITS","eligible":1})

    def test_double_ttl_fresh_then_stale(self):
        quote = dict(self.quote, retrieved_at=self.now-timedelta(seconds=280))
        with self.assertRaises(PriceFreshnessError):
            double_ttl_gate(quote, self.now, self.now+timedelta(seconds=30))

    def test_ttl_rejects_nonfinite(self):
        for ttl in (float("inf"), float("nan"), 0, -1):
            with self.assertRaises(PriceFreshnessError):
                double_ttl_gate(dict(self.quote, ttl_seconds=ttl), self.now, self.now)

    def test_truth_gate_official_pass_blocked(self):
        self.assertEqual(decide_bet(.60, 120, bound=True, fresh=True, deployed=True).bet_status, "OFFICIAL_BET")
        self.assertEqual(decide_bet(.40, 120, bound=True, fresh=True, deployed=True).bet_status, "PASS")
        self.assertEqual(decide_bet(.60, 120, bound=False, fresh=True, deployed=True).bet_status, "BLOCKED")

    def test_truth_gate_rejects_invalid_odds(self):
        for odds in (0, 99, -99, float("inf"), float("nan")):
            with self.assertRaises(TruthGateError):
                decide_bet(.6, odds, bound=True, fresh=True, deployed=True)

    def test_end_to_end_blocks_price_leakage(self):
        model_input = dict(self.key, build_hash="a"*64, sportsbook_probability=.5)
        result = run_candidate(model_input=model_input, quote=self.quote, deployment=self.deploy,
            engine_fn=lambda x: dict(self.key, model_p=.6), ingestion_now=self.now, finalization_now=self.now)
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIn("prohibited", result.reason)

    def test_end_to_end_valid_and_stale(self):
        model_input = dict(self.key, build_hash="a"*64)
        engine = lambda x: dict(self.key, model_p=.60)
        result = run_candidate(model_input=model_input, quote=self.quote, deployment=self.deploy,
            engine_fn=engine, ingestion_now=self.now, finalization_now=self.now)
        self.assertEqual(result.bet_status, "OFFICIAL_BET")
        stale = dict(self.quote, retrieved_at=self.now-timedelta(seconds=301))
        result2 = run_candidate(model_input=model_input, quote=stale, deployment=self.deploy,
            engine_fn=engine, ingestion_now=self.now, finalization_now=self.now)
        self.assertEqual(result2.bet_status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
