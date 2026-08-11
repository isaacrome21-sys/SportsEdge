import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.card_pipeline import run_hitter_card
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def rows(start):
    return [{"player_id": start+i, "slot": i+1, "sequence": 0} for i in range(9)]


def game():
    s = GameSnapshot(
        game_pk=777, game_date="2026-08-10T23:00:00Z", status="Preview",
        away_id=1, away_name="Away", home_id=2, home_name="Home",
        away_probable_pitcher_id=11, away_probable_pitcher_name="A",
        home_probable_pitcher_id=22, home_probable_pitcher_name="H",
        retrieved_at="2026-08-10T19:59:00+00:00",
    )
    return make_live_game(s, rows(100), rows(200))


def feature(pid=100):
    return {"game_pk": 777, "player_id": pid, "team_id": 1, "b_rate": .60, "p_rate": .60, "pa_pool": [4,5,4,5]}


def quote(pid=100, market="HITS"):
    return {
        "game_id": "777", "market": market, "entity_id": str(pid),
        "line": .5, "side": "OVER", "american_odds": 100,
        "retrieved_at": NOW, "ttl_seconds": 300,
    }


def deployed_registry(path):
    path.write_text(json.dumps({
        "schema_version": 1,
        "markets": {
            "HITS": {"eligible": True, "stage": "DEPLOYED", "reason": "test"},
            "TOTAL_BASES": {"eligible": False, "stage": "PRODUCTION_LOGIC_PASS", "reason": "test"},
        },
    }))


class CardPipelineTests(unittest.TestCase):
    def test_checked_in_registry_keeps_hits_blocked(self):
        out = run_hitter_card(games=[game()], feature_rows=[feature()], quotes=[quote()], ingestion_now=NOW, finalization_now=NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertIsNone(out[0].model_p)

    def test_deployed_test_registry_runs_actual_hits_engine_to_official_bet(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "deployments.json"
            deployed_registry(p)
            out = run_hitter_card(games=[game()], feature_rows=[feature()], quotes=[quote()], ingestion_now=NOW, finalization_now=NOW, registry_path=str(p))
        self.assertEqual(out[0].bet_status, "OFFICIAL_BET")
        self.assertIsNotNone(out[0].model_p)
        self.assertGreater(out[0].model_p, .5)

    def test_missing_feature_is_preserved_as_blocked_row(self):
        out = run_hitter_card(games=[game()], feature_rows=[], quotes=[quote()], ingestion_now=NOW, finalization_now=NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertIn("feature snapshot missing", out[0].reason)

    def test_player_not_in_lineup_is_blocked(self):
        out = run_hitter_card(games=[game()], feature_rows=[feature(999)], quotes=[quote(999)], ingestion_now=NOW, finalization_now=NOW)
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertIn("not present", out[0].reason)

    def test_stale_price_blocks_after_successful_assembly(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "deployments.json"
            deployed_registry(p)
            q = quote(); q["ttl_seconds"] = 10
            out = run_hitter_card(games=[game()], feature_rows=[feature()], quotes=[q], ingestion_now=NOW, finalization_now=NOW.replace(minute=1), registry_path=str(p))
        self.assertEqual(out[0].bet_status, "BLOCKED")

    def test_duplicate_quote_is_not_silently_collapsed(self):
        q = quote()
        out = run_hitter_card(games=[game()], feature_rows=[feature()], quotes=[q, dict(q)], ingestion_now=NOW, finalization_now=NOW)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1].bet_status, "BLOCKED")
        self.assertIn("duplicate sportsbook quote", out[1].reason)

    def test_quote_identity_mismatch_blocks(self):
        q = quote(); q["game_id"] = "999"
        out = run_hitter_card(games=[game()], feature_rows=[feature()], quotes=[q], ingestion_now=NOW, finalization_now=NOW)
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertIn("live game missing", out[0].reason)


if __name__ == "__main__":
    unittest.main()
