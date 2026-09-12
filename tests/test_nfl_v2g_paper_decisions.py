import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_nfl_v2g_paper_decisions.py"
spec = importlib.util.spec_from_file_location("build_nfl_v2g_paper_decisions", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NFLV2GPaperDecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = self.root / "policy.json"
        self.pred = self.root / "pred.json"
        self.opener = self.root / "opener.json"
        self.policy.write_text(json.dumps({
            "schema_version": mod.POLICY_SCHEMA,
            "status": "FROZEN_BEFORE_FIRST_WEEK2_OPENER_CAPTURE",
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "frozen_research_artifact_sha256": "e7e591bf1ee7fbf6332cc6795aa1d7126fce9c6a43ac69c164b1f54433457977",
            "paper_selection": {
                "source_window": "OPENER_ONLY",
                "book": "draftkings",
                "markets": ["spreads", "totals"],
                "edge_floor_probability": 0.03,
                "positive_after_vig_ev_required": True,
                "max_minutes_after_opener_retrieval": 120,
                "backfill_allowed": False,
                "staking_allowed": False,
            },
        }), encoding="utf-8")
        self.pred.write_text(json.dumps({
            "schema_version": mod.PRED_SCHEMA,
            "game_id": "2026_02_PIT_NE",
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "artifact_sha256": "e7e591bf1ee7fbf6332cc6795aa1d7126fce9c6a43ac69c164b1f54433457977",
            "prediction_sha256": "a" * 64,
            "away_team": "PIT",
            "home_team": "NE",
            "kickoff_utc": "2026-09-20T17:00:00+00:00",
            "captured_at_utc": "2026-09-12T12:50:13+00:00",
            "market_prices_consumed": False,
            "promotion_authority": False,
            "may_create_model_p": False,
            "market_eligibility_changed": False,
            "official_status_granted": False,
            "score_distribution": [
                {"home_score": 28, "away_score": 17, "margin": 11, "total": 45, "weight": 0.70},
                {"home_score": 17, "away_score": 24, "margin": -7, "total": 41, "weight": 0.30}
            ],
        }), encoding="utf-8")
        self.opener.write_text(json.dumps({
            "capture_kind": "OPENER",
            "week": 2,
            "book": "draftkings",
            "markets": ["spreads", "totals"],
            "retrieved_at_utc": "2026-09-15T14:03:00+00:00",
            "lock_status": "MATCH",
            "games": [{
                "event_id": "evt-1",
                "away_team": "Pittsburgh Steelers",
                "home_team": "New England Patriots",
                "commence_time": "2026-09-20T17:00:00Z",
                "book": "draftkings",
                "spread": {"status": "OK", "home_point": -2.5, "home_price": -110, "away_point": 2.5, "away_price": -110},
                "total": {"status": "OK", "point": 43.5, "over_price": -110, "under_price": -110},
            }],
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, generated="2026-09-15T14:10:00+00:00"):
        return mod.build(self.pred, self.opener, self.policy, generated)

    def test_freezes_paper_candidates_without_authority(self):
        result = self.build()
        self.assertEqual("PAPER_CANDIDATES_FROZEN", result["status"])
        self.assertEqual(2, result["paper_candidate_count"])
        self.assertEqual("home", result["decisions"]["spread"]["selection"]["side"])
        self.assertEqual("over", result["decisions"]["total"]["selection"]["side"])
        self.assertGreaterEqual(result["decisions"]["spread"]["selection"]["edge_probability"], 0.03)
        self.assertGreater(result["decisions"]["spread"]["selection"]["expected_value_units_per_unit"], 0)
        self.assertFalse(result["staking_allowed"])
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["may_create_model_p"])
        self.assertFalse(result["official_status_granted"])
        self.assertEqual(64, len(result["paper_decision_sha256"]))

    def test_rejects_backfill_after_frozen_window(self):
        with self.assertRaises(SystemExit) as ctx:
            self.build("2026-09-15T16:04:01+00:00")
        self.assertIn("NFL_V2G_PAPER_BACKFILL_WINDOW_EXCEEDED", str(ctx.exception))

    def test_rejects_market_contaminated_prediction(self):
        payload = json.loads(self.pred.read_text())
        payload["market_prices_consumed"] = True
        self.pred.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit) as ctx:
            self.build()
        self.assertIn("NFL_V2G_PAPER_PREDICTION_MARKET_LEAKAGE", str(ctx.exception))

    def test_unavailable_market_does_not_invent_decision(self):
        payload = json.loads(self.opener.read_text())
        payload["games"][0]["total"] = {"status": "MISSING"}
        self.opener.write_text(json.dumps(payload))
        result = self.build()
        self.assertEqual("NO_PAPER_DECISION_MARKET_UNAVAILABLE", result["decisions"]["total"]["status"])
        self.assertEqual(1, result["paper_candidate_count"])

    def test_no_vig_edge_with_negative_actual_price_ev_is_not_selected(self):
        payload = json.loads(self.pred.read_text())
        payload["score_distribution"] = [
            {"home_score": 24, "away_score": 17, "margin": 7, "total": 41, "weight": 0.66},
            {"home_score": 17, "away_score": 24, "margin": -7, "total": 41, "weight": 0.34},
        ]
        self.pred.write_text(json.dumps(payload))
        opener = json.loads(self.opener.read_text())
        opener["games"][0]["spread"] = {
            "status": "OK", "home_point": -2.5, "home_price": -200,
            "away_point": 2.5, "away_price": 150
        }
        self.opener.write_text(json.dumps(opener))
        result = self.build()
        spread = result["decisions"]["spread"]
        self.assertEqual("NO_PAPER_EDGE_OR_PRICE", spread["status"])
        top = spread["candidates"][0]
        self.assertGreaterEqual(top["edge_probability"], 0.03)
        self.assertLessEqual(top["expected_value_units_per_unit"], 0)


if __name__ == "__main__":
    unittest.main()
