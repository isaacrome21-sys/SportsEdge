import json
from pathlib import Path
import unittest

from sportsedge.sports.cfb.sportsdataverse_candidate_families import TEAM_METRIC_KEYS
from scripts.run_auto_cfb_resilient import build_card
from sportsedge.sports.cfb.sdv_selected_fit import load_selected_sdv_fit


def _metrics(value):
    row = {key: value for key in TEAM_METRIC_KEYS}
    row.update(season=2025, through_week=3, sample_source="CURRENT_SEASON_PRIOR_WEEKS", games_in_sample=4)
    return row


def _row():
    return {
        "game_id": "g1",
        "neutral_site": False,
        "weather": {"game_indoor": False, "wind_speed": 5, "temperature": 70},
        "home_prior_metrics": _metrics(0.05),
        "away_prior_metrics": _metrics(0.05),
        "home_current_metrics": _metrics(0.2),
        "away_current_metrics": _metrics(0.05),
        "quotes": [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 150},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -180},
        ],
    }


class TestRunAutoCfbResilient(unittest.TestCase):
    def test_positive_edge_is_a_bet_and_no_edge_is_success(self):
        model = load_selected_sdv_fit(Path("config/cfb_sdv_prior_current_blend_fit_v1.json"))
        card = build_card([_row()], model=model)
        self.assertEqual(card["status"], "SUCCESS")
        self.assertEqual(card["family"], "PRIOR_CURRENT_BLEND")
        self.assertEqual(card["ridge_alpha"], 300.0)
        self.assertEqual(card["bakeoff_run"], 37093707442)
        self.assertGreater(card["funnel"]["odds_rows_fetched"], 0)
        self.assertTrue(any(row["model_p"] is not None for row in card["results"]))
        self.assertEqual(card["funnel"]["bets_emitted"], sum(row["edge"] is not None and row["edge"] > 0 for row in card["results"]))
        self.assertNotEqual(card["governance"]["freeze_status"], "FROZEN")
        self.assertIsNone(card["governance"]["artifact_sha256"])
        self.assertFalse(any(row["reason"] == "CFB_PROMOTION_EVIDENCE_REQUIRED" for row in card["results"]))

    def test_zero_quotes_is_the_only_infrastructure_block(self):
        model = load_selected_sdv_fit(Path("config/cfb_sdv_prior_current_blend_fit_v1.json"))
        card = build_card([{"game_id": "g0", "quotes": []}], model=model)
        self.assertEqual(card["funnel"]["odds_rows_fetched"], 0)
        self.assertEqual(card["run_status"], "BLOCKED_NO_ODDS")
        self.assertEqual(card["funnel"]["bets_emitted"], 0)

    def test_workflow_does_not_force_promotion_block(self):
        workflow = Path(".github/workflows/cfb-auto.yml").read_text(encoding="utf-8")
        freeze = json.loads(Path("config/cfb_game_model_freeze.json").read_text(encoding="utf-8"))
        self.assertIn("scripts/run_auto_cfb_resilient.py", workflow)
        self.assertIn("artifacts/live_cfb_card.json", workflow)
        self.assertIn("scripts/render_cfb_myspari_card.py", workflow)
        self.assertIn("CFB_AUTO_FORCED_PROMOTION_BLOCK", workflow)
        self.assertNotIn('row.get("bet_status") != "BLOCKED"', workflow)
        self.assertNotIn("SPORTSEDGE_ODDS_API_KEY", workflow)
        self.assertIn("CFB_MANUAL_BOARD_JSON", workflow)
        self.assertEqual(freeze["status"], "UNFROZEN")
        self.assertIsNone(freeze["artifact_sha256"])


if __name__ == "__main__":
    unittest.main()
