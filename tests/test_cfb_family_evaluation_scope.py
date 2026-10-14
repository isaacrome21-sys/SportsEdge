import unittest
from sportsedge.family_market_registry import family_market_decision


class CfbFamilyScopeTests(unittest.TestCase):
    def test_historical_game_aliases(self):
        for market, family in [('ML', 'moneyline'), ('h2h', 'moneyline'),
                               ('SPREAD', 'spread'), ('spreads', 'spread'),
                               ('point_spread', 'spread'), ('TOTAL', 'total'),
                               ('totals', 'total')]:
            with self.subTest(market=market):
                row = family_market_decision('CFB', market)
                self.assertEqual(row['market'], family)
                self.assertEqual(row['evaluation_scope'], 'HISTORICAL')
                self.assertEqual(row['state'], 'BLOCKED')
                self.assertEqual(row['blocker'], 'NO_VALIDATION')

    def test_team_totals_forward_only_and_unvalidated(self):
        for market in ('TEAM_TOTAL', 'TEAM_TOTALS', 'team_totals', ' team_total '):
            with self.subTest(market=market):
                row = family_market_decision('CFB', market)
                self.assertEqual(row['market'], 'team_total')
                self.assertEqual(row['evaluation_scope'], 'FORWARD_ONLY')
                self.assertEqual(row['state'], 'BLOCKED')
                self.assertEqual(row['blocker'], 'NO_VALIDATION')
                self.assertEqual(row['validation_status'], 'UNVALIDATED')
                for key in ('official_authority', 'model_p_authority', 'staking_authority'):
                    self.assertFalse(row[key])

    def test_unknown_cfb_market_stays_no_engine(self):
        row = family_market_decision('CFB', 'ANYTIME_TD')
        self.assertEqual(row['blocker'], 'NO_ENGINE')
        self.assertEqual(row['evaluation_scope'], 'UNREGISTERED')

    def test_cfb_scope_not_assigned_to_other_sports(self):
        for sport in ('NBA', 'CBB'):
            row = family_market_decision(sport, 'TEAM_TOTAL')
            self.assertEqual(row['blocker'], 'NO_ENGINE')
            self.assertEqual(row['evaluation_scope'], 'UNSPECIFIED')
        self.assertIsNone(family_market_decision('NFL', 'TEAM_TOTAL'))


if __name__ == '__main__':
    unittest.main()
