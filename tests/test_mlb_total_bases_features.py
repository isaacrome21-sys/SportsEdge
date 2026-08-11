import unittest
from datetime import date, datetime, timezone

from sportsedge.mlb_total_bases_features import (
    LG, LG_PH, PARK_ARTIFACT_SHA256, SH, PITCHER_SHRINK,
    MLBTBFeatureError, MLBTBHistorySource, park_factor_for_venue,
)


class MLBTBFeatureTests(unittest.TestCase):
    def test_known_venue_uses_frozen_factor_and_sutter_health_fails_closed(self):
        site, factor = park_factor_for_venue(3313)
        self.assertEqual(site, "NYC21")
        self.assertAlmostEqual(factor, 1.0492658989778996)
        self.assertEqual(PARK_ARTIFACT_SHA256, "d741d7bed908c7f2866509625f854e02dfa76483c9730ce18f23af5fb1b4a6ea")
        with self.assertRaises(MLBTBFeatureError) as cm:
            park_factor_for_venue(2529)
        self.assertEqual(cm.exception.reason, "VENUE_UNMAPPED")

    def test_exact_validated_formula(self):
        src = MLBTBHistorySource(retrieved_at=datetime(2026, 8, 11, 15, tzinfo=timezone.utc))
        bst = {"s": 30, "d": 10, "t": 2, "hr": 8, "pa": 220, "n_start": 40, "pa_pool": [4, 5, 4, 3, 5]}
        pst = {"h": 100, "hr": 15, "bfp": 500}
        src.batter_prior_state = lambda batter_id, target_date: (dict(bst), date(2026, 8, 9))
        src.starter_prior_state = lambda starter_id, target_date: (dict(pst), date(2026, 8, 8))
        values, latest, site = src.build_values(target_date=date(2026, 8, 11), batter_id=1, starter_id=2, venue_id=3313)
        for k in ("s", "d", "t", "hr"):
            self.assertEqual(values["rates"][k], (bst[k] + LG[k] * SH) / (bst["pa"] + SH))
        self.assertEqual(values["p_h"], (pst["h"] + LG_PH * PITCHER_SHRINK) / (pst["bfp"] + PITCHER_SHRINK))
        self.assertEqual(values["p_hr"], (pst["hr"] + LG["hr"] * PITCHER_SHRINK) / (pst["bfp"] + PITCHER_SHRINK))
        self.assertEqual(values["pa_pool"], bst["pa_pool"])
        self.assertEqual(site, "NYC21")
        self.assertEqual(latest, date(2026, 8, 9))

    def test_feature_envelope_matches_shared_bridge_contract(self):
        src = MLBTBHistorySource(retrieved_at=datetime(2026, 8, 11, 15, tzinfo=timezone.utc))
        src.build_values = lambda **kwargs: ({
            "rates": {"s": .14, "d": .05, "t": .004, "hr": .034},
            "p_h": .23, "p_hr": .03, "park": 1.0492658989778996, "pa_pool": [4, 5, 4, 3, 5],
        }, date(2026, 8, 10), "NYC21")
        env = src.feature_envelope(game_pk=777, team_id=1, target_date=date(2026, 8, 11), batter_id=100, starter_id=22, venue_id=3313)
        expected = {"rates_s", "rates_d", "rates_t", "rates_hr", "p_h", "p_hr", "park", "pa_pool"}
        self.assertEqual(set(env["feature_fact_keys"]), expected)
        self.assertEqual(set(env["ttl_by_feature"]), expected)
        self.assertEqual(env["market"], "TOTAL_BASES")
        self.assertEqual(len(env["sources"]), 8)


if __name__ == "__main__":
    unittest.main()
