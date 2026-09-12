import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bind_nfl_v2g_market_evidence.py"
spec = importlib.util.spec_from_file_location("bind_nfl_v2g_market_evidence", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class NFLV2GMarketEvidenceBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pred = self.root / "prediction.json"
        self.opener = self.root / "opener.json"
        self.final = self.root / "final"
        self.final.mkdir()
        self.pred.write_text(json.dumps({
            "schema_version": "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1",
            "game_id": "2026_02_PIT_NE",
            "candidate_id": "nfl_m2_scoring_event_v2g_candidate",
            "away_team": "PIT",
            "home_team": "NE",
            "kickoff_utc": "2026-09-20T17:00:00+00:00",
            "captured_at_utc": "2026-09-12T12:50:13+00:00",
            "prediction_sha256": "a" * 64,
            "artifact_sha256": "b" * 64,
            "implementation_commit_sha": "c" * 40,
            "capture_code_git_sha": "d" * 40,
            "schedule_snapshot_sha256": "e" * 64,
            "market_prices_consumed": False,
            "promotion_authority": False,
            "may_create_model_p": False,
            "market_eligibility_changed": False,
            "official_status_granted": False,
        }), encoding="utf-8")
        self.opener.write_text(
            json.dumps(self.capture("OPENER", "2026-09-15T14:03:00+00:00")),
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def game(*, spread_status="OK", total_status="OK"):
        return {
            "event_id": "evt-1",
            "away_team": "Pittsburgh Steelers",
            "home_team": "New England Patriots",
            "commence_time": "2026-09-20T17:00:00Z",
            "book": "draftkings",
            "book_last_update": "2026-09-15T14:02:30Z",
            "spread": {
                "status": spread_status,
                "home_point": -2.5,
                "home_price": -110,
                "away_point": 2.5,
                "away_price": -110,
            },
            "total": {
                "status": total_status,
                "point": 43.5,
                "over_price": -110,
                "under_price": -110,
            },
        }

    def capture(self, kind, retrieved, *, game=None):
        return {
            "capture_kind": kind,
            "week": 2,
            "book": "draftkings",
            "markets": ["spreads", "totals"],
            "retrieved_at_utc": retrieved,
            "lock_status": "MATCH",
            "games": [game or self.game()],
        }

    def write_final(self, *, game=None, retrieved="2026-09-20T16:31:00+00:00", name="final.json"):
        path = self.final / name
        path.write_text(json.dumps(self.capture("FINAL", retrieved, game=game)), encoding="utf-8")
        return path

    def test_ready_requires_paired_opener_and_final_for_both_markets(self):
        self.write_final()
        result = mod.bind(self.pred, self.opener, list(self.final.glob("*.json")))
        self.assertEqual(mod.READY, result["status"])
        self.assertEqual(mod.READY, result["market_status"]["spread"]["status"])
        self.assertEqual(mod.READY, result["market_status"]["total"]["status"])
        self.assertEqual([], result["missing_components"])
        self.assertEqual("evt-1", result["opener"]["market"]["event_id"])
        self.assertEqual("evt-1", result["final"]["market"]["event_id"])
        self.assertEqual(40, len(result["binding_code_git_blob_sha1"]))
        self.assertFalse(result["market_prices_consumed_by_model"])
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["truth_gate_pass_granted"])
        self.assertFalse(result["official_status_granted"])

    def test_missing_final_is_inconclusive_not_backfilled(self):
        result = mod.bind(self.pred, self.opener, [])
        self.assertEqual(mod.INCONCLUSIVE, result["status"])
        self.assertEqual(mod.INCONCLUSIVE, result["market_status"]["spread"]["status"])
        self.assertEqual(mod.INCONCLUSIVE, result["market_status"]["total"]["status"])
        self.assertIn("final_spread", result["missing_components"])
        self.assertIn("final_total", result["missing_components"])
        self.assertIsNone(result["final"]["market"])

    def test_missing_opener_cannot_be_ready_even_with_valid_final(self):
        self.write_final()
        result = mod.bind(self.pred, None, list(self.final.glob("*.json")))
        self.assertEqual(mod.INCONCLUSIVE, result["status"])
        self.assertIn("opener_spread", result["missing_components"])
        self.assertIn("opener_total", result["missing_components"])

    def test_one_market_can_be_partial_without_promoting_the_other(self):
        self.write_final(game=self.game(total_status="MISSING"))
        result = mod.bind(self.pred, self.opener, list(self.final.glob("*.json")))
        self.assertEqual(mod.PARTIAL, result["status"])
        self.assertEqual(mod.READY, result["market_status"]["spread"]["status"])
        self.assertEqual(mod.INCONCLUSIVE, result["market_status"]["total"]["status"])
        self.assertEqual(["final_total"], result["market_status"]["total"]["missing_components"])

    def test_rejects_market_contaminated_prediction(self):
        payload = json.loads(self.pred.read_text())
        payload["market_prices_consumed"] = True
        self.pred.write_text(json.dumps(payload))
        with self.assertRaises(SystemExit) as ctx:
            mod.bind(self.pred, self.opener, [])
        self.assertIn("NFL_V2G_PREDICTION_MARKET_LEAKAGE", str(ctx.exception))

    def test_rejects_final_at_or_after_kickoff(self):
        self.write_final(retrieved="2026-09-20T17:00:00+00:00", name="late.json")
        with self.assertRaises(SystemExit) as ctx:
            mod.bind(self.pred, self.opener, list(self.final.glob("*.json")))
        self.assertIn("NFL_V2G_FINAL_AFTER_KICKOFF", str(ctx.exception))

    def test_rejects_multiple_final_matches(self):
        self.write_final(name="a.json")
        self.write_final(name="b.json")
        with self.assertRaises(SystemExit) as ctx:
            mod.bind(self.pred, self.opener, list(self.final.glob("*.json")))
        self.assertIn("NFL_V2G_MULTIPLE_FINAL_MATCHES", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
