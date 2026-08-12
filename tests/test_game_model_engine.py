import unittest

from sportsedge.game_model_engine import GameModelError, beta_ml_home_p, price_game_markets

FEATURES = {
    "starter_fip_edge_home": -0.3799999999999999,
    "kbb_edge_home": 0.026999999999999996,
    "lineup_woba_edge_home": -0.0022199999999999998,
    "opp_pct_edge_home": -0.1111111111111111,
    "switch_pct_edge_home": 0.1111111111111111,
}

class GameModelEngineTests(unittest.TestCase):
    def test_ml_anchor_exactly_matches_recovered_beta_v14_fixture(self):
        self.assertEqual(beta_ml_home_p(FEATURES), 0.5372243035771852)

    def test_recovered_run_distribution_parity_on_fixture(self):
        out = price_game_markets(
            ml_features=FEATURES, total_mu=9.400761198126894, vmr=2.226,
            shared_sigma=0.1, seed=8092026, search_sims=1000, final_sims=5000,
            lines=[
                {"key":"home_ml","market":"MONEYLINE","side":"HOME","line":None},
                {"key":"away_ml","market":"MONEYLINE","side":"AWAY","line":None},
                {"key":"home_rl","market":"RUN_LINE","side":"HOME","line":-1.5},
                {"key":"away_rl","market":"RUN_LINE","side":"AWAY","line":1.5},
                {"key":"over9","market":"TOTALS","side":"OVER","line":9},
                {"key":"under9","market":"TOTALS","side":"UNDER","line":9},
            ])
        self.assertEqual(out.home_ml_mc_p, 0.5536)
        self.assertEqual(out.mu_home, 4.996906722709274)
        self.assertEqual(out.mu_away, 4.40385447541762)
        self.assertEqual(out.probabilities["home_ml"], 0.5536)
        self.assertEqual(out.probabilities["away_ml"], 0.4464)
        self.assertEqual(out.probabilities["home_rl"], 0.4108)
        self.assertEqual(out.probabilities["away_rl"], 0.5892)
        self.assertEqual(out.probabilities["over9"], 0.4352)
        self.assertEqual(out.probabilities["under9"], 0.4774)
        self.assertEqual(out.probabilities["over9:push"], 0.0874)
        self.assertEqual(out.probabilities["under9:push"], 0.0874)

    def test_sportsbook_probability_or_price_features_are_rejected(self):
        for key in ("sportsbook_prob", "implied_prob", "american_odds"):
            x = dict(FEATURES); x[key] = 0.5
            with self.assertRaises(GameModelError): beta_ml_home_p(x)

    def test_feature_contract_is_exact(self):
        x = dict(FEATURES); x.pop("kbb_edge_home")
        with self.assertRaises(GameModelError): beta_ml_home_p(x)

if __name__ == "__main__": unittest.main()
