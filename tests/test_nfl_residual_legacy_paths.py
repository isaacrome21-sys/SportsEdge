import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from tests.test_nfl_market_anchored_residual import NOW, game


class LegacyResidualTests(unittest.TestCase):
    def test_m2_replays_original_joint_residuals_at_market_adjusted_center(self):
        from sportsedge.sports.nfl.residual_score_adapter import price_m2_research
        from sportsedge.sports.nfl.m2 import PRODUCTION_NFL_M2_MODEL_ID, NFL_M2_FEATURE_CONTRACT
        model = SimpleNamespace(model_id=PRODUCTION_NFL_M2_MODEL_ID,
            feature_contract=NFL_M2_FEATURE_CONTRACT,
            residual_pairs=((-7.,-8.), (0.,0.), (7.,8.)),
            predict=lambda row: (3.5, 70.5))
        original = model.residual_pairs
        result = price_m2_research(model, {}, game(), as_of=NOW)
        self.assertEqual(result['validated_markets'], [])
        self.assertFalse(result['promotion_authority'])
        self.assertEqual(model.residual_pairs, original)
        self.assertAlmostEqual(result['prices'][0]['fair_total'], 53.5)
        self.assertEqual(len(result['score_paths']), 3)
        self.assertTrue(all(r['eligible_as_bet'] is False for r in result['prices']))

    def test_cli_requires_raw_forecasts_and_never_uses_absolute_estimate_fallback(self):
        from sportsedge.nfl_run_it import main
        with tempfile.TemporaryDirectory() as tmp:
            q=Path(tmp)/'quotes.json'; q.write_text('[]')
            with self.assertRaises(SystemExit):
                main(['--quotes',str(q)])

    def test_cli_dispatches_raw_forecast_to_residual_pricing(self):
        from sportsedge.nfl_run_it import main
        with tempfile.TemporaryDirectory() as tmp:
            q=Path(tmp)/'quotes.json'; q.write_text('[]')
            f=Path(tmp)/'raw.json'; f.write_text('{}')
            with patch('sportsedge.nfl_run_it.run_it_market_anchored', return_value={'picks':[]}) as priced:
                self.assertEqual(main(['--quotes',str(q),'--raw-game-forecasts',str(f), '--as-of',NOW.isoformat()]),0)
                priced.assert_called_once()
