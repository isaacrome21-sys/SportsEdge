import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts.run_mlb_moneyline_shadow_card import (
    MLBShadowCardError,
    american_implied,
    build_shadow_card,
    fair_american,
    load_manual_board,
    price_side,
)


class TestMLBMoneylineShadowCard(unittest.TestCase):
    def test_direct_cli_starts_without_pythonpath(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, "scripts/run_mlb_moneyline_shadow_card.py", "--help"],
            cwd=root, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--slate-date", result.stdout)

    def test_american_math(self):
        self.assertAlmostEqual(american_implied(-150), 0.6)
        self.assertAlmostEqual(american_implied(150), 0.4)
        self.assertAlmostEqual(fair_american(0.6), -150.0)
        self.assertAlmostEqual(fair_american(0.4), 150.0)
        priced = price_side(0.6, 100)
        self.assertAlmostEqual(priced["ev_per_dollar"], 0.2)

    def test_manual_board_requires_two_sided_game_price(self):
        with self.assertRaises(MLBShadowCardError):
            load_manual_board(
                inline_json=json.dumps([{"game_pk": 1, "home_odds": -110}])
            )

    def test_shadow_card_uses_engine_probability_then_manual_dk_price(self):
        snapshot = SimpleNamespace(
            status="Preview",
            game_pk=123,
            away_name="Away",
            home_name="Home",
            game_date="2099-09-19T18:00:00Z",
        )

        def fake_predictor(**kwargs):
            self.assertEqual(kwargs["snapshot"].game_pk, 123)
            return {
                "model_p": 0.60,
                "event_start_ts": "2099-09-19T18:00:00+00:00",
                "production_engine_dispatch": "sportsedge.engine_registry.engine_registry[MONEYLINE]",
                "engine_version": "TEST_ENGINE",
                "model_artifact_sha256": "a" * 64,
                "feature_source_hash": "b" * 64,
                "distribution_sha256": "c" * 64,
                "mc_paths": 100000,
                "market_blind": True,
            }

        card = build_shadow_card(
            schedule=[snapshot],
            history=object(),
            now=datetime(2026, 9, 19, tzinfo=timezone.utc),
            dk_rows=[{"game_pk": 123, "home_odds": 100, "away_odds": -120}],
            dk_source="MANUAL_JSON_INLINE",
            predictor=fake_predictor,
        )
        self.assertEqual(card["status"], "PAPER_ONLY")
        self.assertEqual(card["label"], "SHADOW_P")
        self.assertFalse(any(card["authority"].values()))
        self.assertEqual(len(card["games"]), 1)
        game = card["games"][0]
        self.assertEqual(game["status"], "SHADOW_P_PAPER_ONLY")
        self.assertAlmostEqual(game["shadow_p_home"], 0.60)
        self.assertIsNone(game["governed_model_p"])
        self.assertTrue(game["paper_candidate"])
        self.assertEqual(game["paper_side"], "HOME")
        self.assertGreater(game["paper_ev_per_dollar"], 0.0)
        self.assertFalse(game["official"])
        self.assertFalse(game["truth_gate"])

    def test_without_dk_price_probability_is_still_shadow_output_not_bet(self):
        snapshot = SimpleNamespace(
            status="Preview",
            game_pk=456,
            away_name="Away",
            home_name="Home",
            game_date="2099-09-19T18:00:00Z",
        )

        def fake_predictor(**kwargs):
            return {
                "model_p": 0.55,
                "event_start_ts": "2099-09-19T18:00:00+00:00",
                "market_blind": True,
            }

        card = build_shadow_card(
            schedule=[snapshot],
            history=object(),
            now=datetime(2026, 9, 19, tzinfo=timezone.utc),
            predictor=fake_predictor,
        )
        game = card["games"][0]
        self.assertFalse(game["paper_candidate"])
        self.assertIsNone(game["paper_side"])
        self.assertNotIn("draftkings", game)
        self.assertFalse(any(card["authority"].values()))


if __name__ == "__main__":
    unittest.main()
