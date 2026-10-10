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

        no_edge = build_card([_row(-5000)], model=model)
        self.assertEqual(no_edge["run_status"], "READY")
        self.assertEqual(no_edge["results"][0]["bet_status"], "NO_BET")
        self.assertEqual(no_edge["results"][0]["reason"], "NO_EDGE")
        self.assertEqual(no_edge["funnel"]["bets_emitted"], 0)

    def test_documented_manual_json_binds_and_prices_side_lines(self):
        from types import SimpleNamespace
        from scripts.run_auto_cfb_resilient import _group_manual_quotes, _side_probability

        games = [SimpleNamespace(game_id="g-pitt", home_team="Pittsburgh", away_team="North Carolina")]
        aliases = {"pittsburgh": "Pittsburgh", "north carolina": "North Carolina"}
        manual_board = [{
            "home": "Pittsburgh", "away": "North Carolina", "quotes": [
                {"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
                {"market": "SPREAD", "side": "AWAY", "line": 3.5, "american_odds": -110},
                {"market": "TOTAL", "side": "OVER", "line": 47.5, "american_odds": -110},
                {"market": "TOTAL", "side": "UNDER", "line": 47.5, "american_odds": -110},
            ],
        }]
        grouped = _group_manual_quotes(manual_board, games=games, alias_index=aliases)
        quotes = grouped["g-pitt"]
        self.assertEqual(len(quotes), 4)
        self.assertTrue(all(q["book_key"] == "draftkings" for q in quotes))
        home_p = _side_probability(27, 23, quotes[0])
        away_p = _side_probability(27, 23, quotes[1])
        self.assertAlmostEqual(home_p + away_p, 1.0, places=10)
        self.assertAlmostEqual(
            _side_probability(27, 23, quotes[2]) +
            _side_probability(27, 23, quotes[3]), 1.0, places=10,
        )

    def test_unmatched_manual_game_fails_closed(self):
        from types import SimpleNamespace
        from scripts.run_auto_cfb_resilient import _group_manual_quotes
        with self.assertRaisesRegex(ValueError, "MATCHUP_UNRESOLVED"):
            _group_manual_quotes(
                [{"home": "Pittsburgh", "away": "Wrong", "quotes": [
                    {"market": "TOTAL", "side": "OVER", "line": 48.5, "american_odds": -110},
                ]}],
                games=[SimpleNamespace(game_id="g-pitt", home_team="Pittsburgh", away_team="Wrong Else")],
                alias_index={"pittsburgh": "Pittsburgh", "wrong": "Wrong"},
            )

    def test_unpriced_quotes_block_instead_of_returning_empty_ready_card(self):
        from scripts.run_auto_cfb_resilient import build_card
        row = _row(-110)
        row.pop("home_prior_metrics")
        row.pop("home_current_metrics")
        card = build_card([row], model=None)
        self.assertEqual(card["run_status"], "BLOCKED_MODEL_UNAVAILABLE")
        self.assertEqual(card["funnel"]["model_priced"], 0)
        self.assertEqual(card["funnel"]["pipeline_health"], "BROKEN")


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
        self.assertIn("artifacts/live_cfb_card.json", workflow)
        self.assertIn("render_cfb_myspari_card.py", workflow)
        self.assertNotIn("SPORTSEDGE_ODDS_API_KEY", workflow)


if __name__ == "__main__":
    unittest.main()
