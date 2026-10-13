import json
import unittest
from pathlib import Path

from sportsedge import mlb_pregame_starter_adapter as a

BOUND = {"binding_status": "RESEARCH_BOUND", "block_reason": None, "game_pk": 1,
         "pricing_authorized": False, "betting_authorized": False, "model_eligible": False,
         "promotion_authority": False, "max_action": "WATCH",
         "away_probable_id": 100, "home_probable_id": 200}
KW = {"game_pk": 1}


def b(out):
    return lambda **kw: dict(out)


class AdapterTests(unittest.TestCase):
    def assert_zero(self, r):
        for k in ("pricing_authorized", "betting_authorized", "model_eligible", "promotion_authority", "activation"):
            self.assertIs(r[k], False)
        self.assertIn(r["max_action"], ("NONE", "WATCH"))

    def test_bound_f5_nrfi_watch(self):
        for fam in sorted(a.F5_FAMILIES | a.FIRST_INNING_FAMILIES):
            r = a.gate_market_on_pregame_starters(fam, binding_kwargs=KW, binder=b(BOUND))
            self.assertEqual(r["status"], "WATCH")
            self.assertEqual(r["max_action"], "WATCH")
            self.assert_zero(r)

    def test_pitcher_prop_requires_bound_pitcher(self):
        r = a.gate_market_on_pregame_starters("PITCHER_STRIKEOUTS", binding_kwargs=KW, pitcher_id=200, binder=b(BOUND))
        self.assertEqual((r["status"], r["pitcher_side"]), ("WATCH", "home"))
        r = a.gate_market_on_pregame_starters("PITCHER_STRIKEOUTS", binding_kwargs=KW, pitcher_id=999, binder=b(BOUND))
        self.assertEqual(r["block_reason"], "PITCHER_NOT_BOUND_PREGAME_STARTER")
        for bad in (None, 0, -1, "200", 200.0, True):
            r = a.gate_market_on_pregame_starters("PITCHER_OUTS", binding_kwargs=KW, pitcher_id=bad, binder=b(BOUND))
            self.assertEqual(r["status"], "BLOCKED", bad)

    def test_loader_blocks_propagate(self):
        for reason in ("ID_MISSING", "POSTPONED_NOT_IDENTITY_EVIDENCE", "RECEIPT_AFTER_AS_OF",
                       "OBSERVED_ONLY_NOT_IDENTITY_EVIDENCE", "AS_OF_NOT_PREGAME"):
            out = {"binding_status": "BLOCKED", "block_reason": reason}
            r = a.gate_market_on_pregame_starters("NRFI", binding_kwargs=KW, binder=b(out))
            self.assertEqual(r["status"], "BLOCKED")
            self.assertIn(reason, r["block_reason"])
            self.assert_zero(r)

    def test_malformed_binder_outputs_fail_closed(self):
        bads = [None, [], "x", {}, dict(BOUND, binding_status="BOUND"),
                dict(BOUND, pricing_authorized=True), dict(BOUND, model_eligible=None),
                dict(BOUND, max_action="BET"), dict(BOUND, away_probable_id="100"),
                dict(BOUND, home_probable_id=True), dict(BOUND, home_probable_id=100)]
        for out in bads:
            r = a.gate_market_on_pregame_starters("F5_TOTALS", binding_kwargs=KW, binder=lambda **k: out)
            self.assertEqual(r["status"], "BLOCKED", out)
            self.assert_zero(r)

    def test_binder_exception_fails_closed(self):
        def boom(**k):
            raise OSError("x")
        r = a.gate_market_on_pregame_starters("YRFI", binding_kwargs=KW, binder=boom)
        self.assertEqual(r["block_reason"], "BINDER_ERROR:OSError")

    def test_unsupported_and_not_offered(self):
        for fam in ("MLB_STOLEN_BASES", "STOLEN_BASES", "MONEYLINE", None, 5):
            r = a.gate_market_on_pregame_starters(fam, binding_kwargs=KW, binder=b(BOUND))
            self.assertEqual(r["status"], "BLOCKED")
        r = a.gate_market_on_pregame_starters("NRFI", binding_kwargs=None, binder=b(BOUND))
        self.assertEqual(r["block_reason"], "BINDING_KWARGS_INVALID")

    def test_real_loader_blocks_without_evidence(self, ):
        import tempfile
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            kw = dict(capture_path=d / "c.jsonl", manifest_path=d / "m.json", raw_dir=d / "raw",
                      receipt_root=d / "r", game_pk=1, as_of=datetime(2027, 4, 1, tzinfo=timezone.utc),
                      plan_first_pitch_utc="2027-04-01T23:00:00Z")
            r = a.gate_market_on_pregame_starters("F5_MONEYLINE", binding_kwargs=kw)
            self.assertEqual(r["status"], "BLOCKED")
            self.assert_zero(r)

    def test_f5_deployments_untouched(self):
        found = []

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if isinstance(k, str) and k.startswith("F5_") and isinstance(v, dict) and "eligible" in v:
                        found.append((k, v["eligible"]))
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(json.loads(Path("config/deployments.json").read_text()))
        self.assertTrue(found)
        self.assertTrue(all(e is False for _, e in found), found)

if __name__ == "__main__":
    unittest.main()
