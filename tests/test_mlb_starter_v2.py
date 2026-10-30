"""Unit tests for starter v2 — constants must match pre-lock; pure math only."""
from __future__ import annotations

import unittest

from sportsedge.mlb_starter_v2 import (
    BB_COEF,
    CONSTANTS,
    CONSTANTS_SHA256,
    DEFAULT_INNINGS_SHARE,
    HR_COEF,
    INNINGS_SHARE_HI,
    INNINGS_SHARE_LO,
    K_COEF,
    K_GAIN,
    LEAGUE_RA9_PROXY,
    SHRINKAGE_PRIOR_IP,
    SPEC_VERSION,
    STARTER_PROFILE_MINIMUM_STARTS,
    STARTER_PROFILE_WINDOW_STARTS,
    LeagueRateBaseline,
    StarterPeripheralProfile,
    adjust_shell_mean,
    constants_receipt,
    defense_blend_shell,
    innings_share,
    peripheral_profile_from_start_rows,
    shrink_residual,
    starter_ra9_hat,
    starter_v2_means,
)
from sportsedge.source_lineage import canonical_json_sha256

EXPECTED_CONSTANTS_SHA256 = "c349df6bbb38c8507440e86421649100ae88a636adc683d975fe6853dbd0158c"


class StarterV2ConstantsTests(unittest.TestCase):
    def test_prelock_values(self):
        self.assertEqual(LEAGUE_RA9_PROXY, 4.50)
        self.assertEqual(K_GAIN, 1.0)
        self.assertEqual(SHRINKAGE_PRIOR_IP, 50.0)
        self.assertEqual(DEFAULT_INNINGS_SHARE, 0.55)
        self.assertEqual(INNINGS_SHARE_LO, 0.45)
        self.assertEqual(INNINGS_SHARE_HI, 0.65)
        self.assertEqual(STARTER_PROFILE_WINDOW_STARTS, 12)
        self.assertEqual(STARTER_PROFILE_MINIMUM_STARTS, 3)
        self.assertEqual(BB_COEF, 9.0)
        self.assertEqual(K_COEF, 6.0)
        self.assertEqual(HR_COEF, 39.0)
        self.assertEqual(CONSTANTS["starter_profile_window_starts"], 12)
        self.assertEqual(CONSTANTS["starter_profile_minimum_starts"], 3)
        self.assertEqual(CONSTANTS["league_rate_window"], {"start": "2026-06-01", "end": "2026-07-31"})
        self.assertEqual(CONSTANTS["evaluation_window"], {"start": "2026-08-01", "end": "2026-08-31"})

    def test_constants_hash_stable(self):
        self.assertEqual(CONSTANTS_SHA256, canonical_json_sha256(CONSTANTS))
        self.assertEqual(CONSTANTS_SHA256, EXPECTED_CONSTANTS_SHA256)
        receipt = constants_receipt()
        self.assertEqual(receipt["constants_sha256"], CONSTANTS_SHA256)


class StarterV2MathTests(unittest.TestCase):
    def setUp(self):
        self.league = LeagueRateBaseline(k_rate=0.25, bb_rate=0.10, hr_rate=0.04, total_outs=10000.0)

    def test_ra9_hat_league_average_is_proxy(self):
        hat = starter_ra9_hat(
            k_rate=self.league.k_rate,
            bb_rate=self.league.bb_rate,
            hr_rate=self.league.hr_rate,
            league=self.league,
        )
        self.assertAlmostEqual(hat, LEAGUE_RA9_PROXY, places=12)

    def test_fip_unit_conversion_per_out(self):
        one_per_nine = 1.0 / 27.0
        hr_hat = starter_ra9_hat(
            k_rate=self.league.k_rate,
            bb_rate=self.league.bb_rate,
            hr_rate=self.league.hr_rate + one_per_nine,
            league=self.league,
        )
        bb_hat = starter_ra9_hat(
            k_rate=self.league.k_rate,
            bb_rate=self.league.bb_rate + one_per_nine,
            hr_rate=self.league.hr_rate,
            league=self.league,
        )
        k_hat = starter_ra9_hat(
            k_rate=self.league.k_rate + one_per_nine,
            bb_rate=self.league.bb_rate,
            hr_rate=self.league.hr_rate,
            league=self.league,
        )
        self.assertAlmostEqual(hr_hat - LEAGUE_RA9_PROXY, 13.0 / 9.0, places=12)
        self.assertAlmostEqual(bb_hat - LEAGUE_RA9_PROXY, 3.0 / 9.0, places=12)
        self.assertAlmostEqual(k_hat - LEAGUE_RA9_PROXY, -2.0 / 9.0, places=12)

    def test_high_k_lowers_ra9(self):
        hat = starter_ra9_hat(
            k_rate=self.league.k_rate + 0.05,
            bb_rate=self.league.bb_rate,
            hr_rate=self.league.hr_rate,
            league=self.league,
        )
        self.assertLess(hat, LEAGUE_RA9_PROXY)

    def test_shrinkage_zero_ip_is_zero(self):
        self.assertEqual(shrink_residual(residual=2.0, observed_ip=0.0), 0.0)

    def test_shrinkage_infinite_ip_approaches_residual(self):
        self.assertAlmostEqual(shrink_residual(residual=2.0, observed_ip=1e9), 2.0, places=6)

    def test_shrinkage_at_prior(self):
        self.assertAlmostEqual(shrink_residual(residual=2.0, observed_ip=50.0), 1.0, places=12)

    def test_innings_share_default_and_clip(self):
        self.assertEqual(innings_share(None), DEFAULT_INNINGS_SHARE)
        self.assertEqual(innings_share(0.0), DEFAULT_INNINGS_SHARE)
        self.assertAlmostEqual(innings_share(14.85), 0.55, places=12)
        self.assertEqual(innings_share(5.0), INNINGS_SHARE_LO)
        self.assertEqual(innings_share(27.0), INNINGS_SHARE_HI)

    def test_neutral_starter_leaves_shell(self):
        starter = StarterPeripheralProfile(1, 0, 0.0, None, None, None, None, "INSUFFICIENT_PRIOR_STARTS")
        out = adjust_shell_mean(shell=4.2, starter=starter, team_runs_against_mean=4.5, league=self.league)
        self.assertFalse(out["applied"])
        self.assertEqual(out["adjusted_mean"], 4.2)

    def test_defense_blend_shell(self):
        self.assertAlmostEqual(defense_blend_shell(away_runs_for=5.0, home_runs_against=4.0), 4.5)

    def test_v2_means_structure(self):
        available = StarterPeripheralProfile(99, 5, 75.0, 0.30, 0.08, 0.03, 15.0, "AVAILABLE")
        weak = StarterPeripheralProfile(100, 5, 75.0, 0.18, 0.14, 0.06, 15.0, "AVAILABLE")
        result = starter_v2_means(
            away_runs_for=4.5,
            away_runs_against=4.5,
            home_runs_for=4.5,
            home_runs_against=4.5,
            away_starter=available,
            home_starter=weak,
            league=self.league,
        )
        self.assertEqual(result["research_version"], SPEC_VERSION)
        self.assertEqual(result["constants_sha256"], CONSTANTS_SHA256)
        self.assertFalse(result["starter_identity_pit_verified"])
        self.assertGreater(result["away_mean_runs"], result["away_shell"])
        self.assertLess(result["home_mean_runs"], result["home_shell"])

    def test_peripheral_profile_from_rows(self):
        rows = [
            {"outs": 15.0, "strikeouts": 6, "walks": 2, "home_runs": 1},
            {"outs": 18.0, "strikeouts": 8, "walks": 1, "home_runs": 0},
            {"outs": 12.0, "strikeouts": 4, "walks": 3, "home_runs": 1},
        ]
        profile = peripheral_profile_from_start_rows(player_id=7, rows=rows, minimum=3)
        self.assertEqual(profile.status, "AVAILABLE")
        self.assertEqual(profile.starts, 3)
        self.assertAlmostEqual(profile.total_outs, 45.0)


if __name__ == "__main__":
    unittest.main()
