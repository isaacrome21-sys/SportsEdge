import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa", "passing_down_success_rate",
    "net_field_position", "explosive_rate",
)


def _metrics(bias: float) -> dict:
    return {key: bias for key in KEYS} | {"games_in_sample": 6}


def _row(odds: int) -> dict:
    return {
        "game_id": "g1",
        "home_team": "Home",
        "away_team": "Away",
        "neutral_site": False,
        "weather": {"game_indoor": True},
        "home_prior_metrics": _metrics(0.2),
        "home_current_metrics": _metrics(0.3),
        "away_prior_metrics": _metrics(-0.1),
        "away_current_metrics": _metrics(-0.2),
        "quotes": [{"market": "MONEYLINE", "side": "HOME", "american_odds": odds}],
    }


class RunAutoCfbResilientTest(unittest.TestCase):
    def test_positive_edge_is_a_bet_and_no_edge_is_success(self):
        from scripts.run_auto_cfb_resilient import build_card
        from sportsedge.sports.cfb.sdv_selected_fit import load_selected_sdv_fit

        model = load_selected_sdv_fit(ROOT / "config/cfb_sdv_prior_current_blend_fit_v1.json")
        priced = build_card([_row(500)], model=model)
        self.assertEqual(priced["run_status"], "READY")
        self.assertEqual(priced["status"], "SUCCESS")
        self.assertIsNotNone(priced["results"][0]["model_p"])
        self.assertGreater(priced["results"][0]["edge"], 0)
        self.assertEqual(priced["results"][0]["bet_status"], "BET")
        self.assertEqual(priced["funnel"]["bets_emitted"], 1)
        self.assertEqual(priced["governance"]["freeze_status"], "UNFROZEN")
        self.assertIsNone(priced["governance"]["artifact_sha256"])
        self.assertFalse(priced["governance"]["odds_api_called"])
        self.assertEqual(priced["family"], "PRIOR_CURRENT_BLEND")
        self.assertEqual(priced["bakeoff_run"], 37093707442)
        self.assertTrue(priced["summary"]["both_sides"])
        self.assertTrue(priced["summary"]["catalog_complete"])
        self.assertFalse(priced["summary"]["invented_lines"])
        self.assertEqual(priced["summary"]["side_rows"], 2)
        away = [row for row in priced["results"] if row["side"] == "AWAY"][0]
        self.assertIsNone(away["american_odds"])
        self.assertEqual(away["bet_status"], "NO_BET")

        no_edge = build_card([_row(-5000)], model=model)
        self.assertEqual(no_edge["run_status"], "READY")
        self.assertEqual(no_edge["results"][0]["bet_status"], "NO_BET")
        self.assertEqual(no_edge["results"][0]["reason"], "NO_EDGE")
        self.assertEqual(no_edge["funnel"]["bets_emitted"], 0)

    def test_zero_quotes_is_the_only_infrastructure_block(self):
        env = dict(os.environ)
        env["CFB_MANUAL_BOARD_JSON"] = "[]"
        out = ROOT / "artifacts" / "live_cfb_card_test.json"
        proc = subprocess.run(
            [sys.executable, "scripts/run_auto_cfb_resilient.py", "--output", str(out)],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 2)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["run_status"], "BLOCKED_NO_ODDS")
        self.assertEqual(payload["funnel"]["odds_rows_fetched"], 0)
        workflow = (ROOT / ".github/workflows/cfb-auto.yml").read_text(encoding="utf-8")
        self.assertIn("scripts/run_auto_cfb_resilient.py", workflow)
        self.assertIn("CFB_AUTO_FORCED_PROMOTION_BLOCK", workflow)
        self.assertNotIn("run_cfb_auto.py", workflow)
        self.assertNotIn("CFB_AUTO_PROP_SIDE_TOTAL_COVERAGE", workflow)
        self.assertIn("artifacts/live_cfb_card.json", workflow)
        self.assertIn("render_cfb_myspari_card.py", workflow)
        self.assertNotIn("SPORTSEDGE_ODDS_API_KEY", workflow)


if __name__ == "__main__":
    unittest.main()
