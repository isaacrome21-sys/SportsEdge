import unittest

from sportsedge.sports.cfb.m2 import _assert_market_blind, build_cfb_m2_features


class CFBM2MarketLeakageAliasTests(unittest.TestCase):
    def test_aliases_match_nfl_guard_surface(self):
        for key in (
            "home_spread", "consensus_total", "sportsbook_price", "closing_odds",
            "opening_spread", "book_total", "market_implied_probability",
        ):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "M2_MARKET_DATA_PROHIBITED"):
                _assert_market_blind({key: 1})

    def test_pattern_aliases_are_rejected_nested(self):
        payload = {"safe": [{"feature_vendor_implied_probability_v2": 0.61}]}
        with self.assertRaisesRegex(ValueError, r"root.safe\[0\]"):
            _assert_market_blind(payload)
        with self.assertRaisesRegex(ValueError, "M2_MARKET_DATA_PROHIBITED"):
            _assert_market_blind({"x_no_vig_probability_snapshot": 0.5})

    def test_legitimate_football_features_still_build(self):
        source = {
            "feature_asof_ts": "2026-08-28T12:00:00+00:00",
            "game_start_ts": "2026-08-29T16:00:00+00:00",
            "off_epa": 0.18,
            "def_epa": -0.05,
            "opp_off_epa": 0.10,
            "opp_def_epa": 0.02,
            "returning_production": 0.72,
            "prior_rating": 8.3,
            "venue_hfa": 2.1,
        }
        out = build_cfb_m2_features(source)
        self.assertAlmostEqual(out["adj_off_eff"], 0.16)
        self.assertAlmostEqual(out["adj_def_eff"], -0.15)


if __name__ == "__main__":
    unittest.main()
