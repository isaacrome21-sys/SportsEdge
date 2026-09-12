import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "settle_nfl_v2g_prospective.py"
spec = importlib.util.spec_from_file_location("settle_nfl_v2g_prospective", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NFLV2GProspectiveSettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = self.root / "policy.json"
        self.pred = self.root / "pred.json"
        self.paper = self.root / "paper.json"
        self.binding = self.root / "binding.json"
        self.games = self.root / "games.csv"
        artifact = "e7e591bf1ee7fbf6332cc6795aa1d7126fce9c6a43ac69c164b1f54433457977"
        self.policy.write_text(json.dumps({
            "schema_version": mod.POLICY_SCHEMA,
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "frozen_research_artifact_sha256": artifact,
        }), encoding="utf-8")
        self.pred.write_text(json.dumps({
            "schema_version": mod.PRED_SCHEMA,
            "game_id": "2026_02_PIT_NE",
            "season": 2026,
            "week": 2,
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "artifact_sha256": artifact,
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
        self.paper.write_text(json.dumps({
            "schema_version": mod.PAPER_SCHEMA,
            "game_id": "2026_02_PIT_NE",
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "artifact_sha256": artifact,
            "prediction_sha256": "a" * 64,
            "paper_decision_sha256": "b" * 64,
            "decision_generated_at_utc": "2026-09-15T14:10:00+00:00",
            "market_prices_consumed_by_model": False,
            "promotion_authority": False,
            "may_create_model_p": False,
            "market_eligibility_changed": False,
            "official_status_granted": False,
            "decisions": {
                "spread": {"status": "PAPER_CANDIDATE", "selection": {
                    "side": "home", "selection": "NE", "line": -2.5, "price": -110,
                    "market_no_vig_probability": 0.5, "edge_probability": 0.20,
                    "expected_value_units_per_unit": 0.3363636364
                }},
                "total": {"status": "PAPER_CANDIDATE", "selection": {
                    "side": "over", "selection": "OVER", "line": 43.5, "price": -110,
                    "market_no_vig_probability": 0.5, "edge_probability": 0.20,
                    "expected_value_units_per_unit": 0.3363636364
                }}
            }
        }), encoding="utf-8")
        self.binding.write_text(json.dumps({
            "schema_version": mod.BINDING_SCHEMA,
            "status": "READY_FOR_PROSPECTIVE_EVALUATION",
            "game_id": "2026_02_PIT_NE",
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "prediction": {"prediction_sha256": "a" * 64},
            "market_prices_consumed_by_model": False,
            "promotion_authority": False,
            "may_create_model_p": False,
            "market_eligibility_changed": False,
            "official_status_granted": False,
            "final": {"market": {
                "spread": {"status": "OK", "home_point": -2.5, "home_price": -120, "away_point": 2.5, "away_price": 100},
                "total": {"status": "OK", "point": 43.5, "over_price": -120, "under_price": 100}
            }}
        }), encoding="utf-8")
        self.games.write_text(
            "game_id,season,week,home_team,away_team,home_score,away_score\n"
            "2026_02_PIT_NE,2026,2,NE,PIT,27,17\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, binding=True):
        return mod.build(
            self.pred,
            self.paper,
            self.binding if binding else None,
            self.games,
            self.policy,
            "2026-09-20T21:00:00+00:00",
        )

    def test_scores_prediction_against_close_and_paper_roi(self):
        result = self.build()
        self.assertEqual("SETTLED_PROSPECTIVE_EVIDENCE", result["status"])
        self.assertEqual("SCORED", result["predictive_evaluation"]["spread"]["status"])
        self.assertEqual("SCORED", result["predictive_evaluation"]["total"]["status"])
        self.assertTrue(result["predictive_evaluation"]["spread"]["model_beats_close_log_loss"])
        self.assertEqual("WIN", result["paper_evaluation"]["spread"]["result"])
        self.assertEqual("WIN", result["paper_evaluation"]["total"]["result"])
        self.assertGreater(result["paper_evaluation"]["spread"]["after_vig_profit_units"], 0)
        self.assertEqual("COMPARABLE_SAME_LINE", result["paper_evaluation"]["spread"]["clv"]["status"])
        self.assertGreater(result["paper_evaluation"]["spread"]["clv"]["probability_clv"], 0)
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["official_status_granted"])
        self.assertEqual(64, len(result["outcome_source_snapshot_sha256"]))

    def test_missing_close_is_inconclusive_not_backfilled(self):
        result = self.build(binding=False)
        self.assertEqual("SETTLED_INCONCLUSIVE_MISSING_CAPTURE", result["status"])
        self.assertEqual("INCONCLUSIVE_MISSING_CAPTURE", result["predictive_evaluation"]["spread"]["status"])
        self.assertEqual("WIN", result["paper_evaluation"]["spread"]["result"])
        self.assertEqual("INCONCLUSIVE_MISSING_CAPTURE", result["paper_evaluation"]["spread"]["clv"]["status"])

    def test_outcome_without_final_score_does_not_settle(self):
        self.games.write_text(
            "game_id,season,week,home_team,away_team,home_score,away_score\n"
            "2026_02_PIT_NE,2026,2,NE,PIT,,\n",
            encoding="utf-8",
        )
        result = self.build()
        self.assertEqual("OUTCOME_NOT_FINAL", result["status"])

    def test_changed_line_keeps_line_clv_but_not_probability_clv(self):
        payload = json.loads(self.binding.read_text())
        payload["final"]["market"]["spread"]["home_point"] = -3.5
        payload["final"]["market"]["spread"]["away_point"] = 3.5
        self.binding.write_text(json.dumps(payload))
        result = self.build()
        clv = result["paper_evaluation"]["spread"]["clv"]
        self.assertEqual("NOT_COMPARABLE_LINE_CHANGED", clv["status"])
        self.assertEqual(1.0, clv["line_clv"])
        self.assertIsNone(clv["probability_clv"])

    def test_rejects_post_kickoff_paper_decision(self):
        payload = json.loads(self.paper.read_text())
        payload["decision_generated_at_utc"] = "2026-09-20T17:01:00+00:00"
        self.paper.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit) as ctx:
            self.build()
        self.assertIn("NFL_V2G_SETTLEMENT_PAPER_NOT_PREGAME", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
