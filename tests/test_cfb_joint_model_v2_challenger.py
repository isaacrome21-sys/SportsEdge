"""Tests for the CFB V2 dispersion challenger (candidate only, no Model_P)."""
import unittest

import numpy as np

from sportsedge.sports.cfb.joint_model import _TEAM_KEYS, fit_cfb_joint_score_model
from sportsedge.sports.cfb.joint_model_v2_challenger import (
    CFB_V2_STATUS,
    CFBChallengerError,
    fit_cfb_v2_challenger,
    key_number_mass,
    outcome_calibration,
    price_paths,
    simulate_cfb_v2_paths,
)


def _rows(seasons, n=80, seed=7):
    rng = np.random.default_rng(seed)
    out = []
    for season in seasons:
        for g in range(n):
            oh, oa = rng.normal(0, 1, 2)
            hm = {k: float(rng.normal(0, 0.3)) for k in _TEAM_KEYS}
            am = {k: float(rng.normal(0, 0.3)) for k in _TEAM_KEYS}
            hm["points_per_drive"] += oh
            am["points_per_drive"] += oa
            mh, ma = 30 + 7 * oh, 27 + 7 * oa
            h = max(0, int(round(mh + np.sqrt(max(mh, 4)) * 2 * rng.normal())))
            a = max(0, int(round(ma + np.sqrt(max(ma, 4)) * 2 * rng.normal())))
            row = {
                "game_id": f"{season}-{g}", "season": season, "neutral_site": False,
                "home_metrics": hm, "away_metrics": am, "weather": {"game_indoor": True},
                "home_score": h, "away_score": a,
            }
            if h == a:
                row.update(regulation_home_score=h, regulation_away_score=a, home_score=h + 7)
            out.append(row)
    return out


class ChallengerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _rows((2022, 2023, 2024))
        cls.model = fit_cfb_v2_challenger(cls.rows)

    def test_status_is_candidate_only(self):
        self.assertEqual(self.model.status, CFB_V2_STATUS)
        self.assertIn("NO_MODEL_P", self.model.status)

    def test_residuals_are_forward_chained_only(self):
        # Earliest season never contributes residuals; later seasons each do.
        self.assertEqual(self.model.residual_seasons, (2023, 2024))
        self.assertEqual(len(self.model.standardized_pairs), 160)

    def test_mean_model_is_v1_unchanged(self):
        v1 = fit_cfb_joint_score_model(self.rows)
        self.assertEqual(self.model.base.artifact_sha256(), v1.artifact_sha256())
        self.assertEqual(self.model.predict_means(self.rows[0]), v1.predict_means(self.rows[0]))

    def test_single_season_fails_closed(self):
        with self.assertRaises(CFBChallengerError):
            fit_cfb_v2_challenger(_rows((2024,), n=150))

    def test_deterministic_and_seed_sensitive(self):
        r = self.rows[5]
        a1 = simulate_cfb_v2_paths(self.model, r, seed=11, n_paths=2000)
        a2 = simulate_cfb_v2_paths(self.model, r, seed=11, n_paths=2000)
        b = simulate_cfb_v2_paths(self.model, r, seed=12, n_paths=2000)
        self.assertTrue(np.array_equal(a1[0], a2[0]) and np.array_equal(a1[1], a2[1]))
        self.assertFalse(np.array_equal(a1[0], b[0]))

    def test_no_ties_no_negative_scores(self):
        h, a = simulate_cfb_v2_paths(self.model, self.rows[3], seed=3, n_paths=5000)
        self.assertFalse(np.any(h == a))
        self.assertTrue(np.all(h >= 0) and np.all(a >= 0))

    def test_scale_grows_with_mean(self):
        self.assertGreater(float(self.model.home_scale.at(50.0)), float(self.model.home_scale.at(15.0)))

    def test_pricing_partitions_to_one(self):
        h, a = simulate_cfb_v2_paths(self.model, self.rows[1], seed=5, n_paths=4000)
        p = price_paths(h, a, spread_line=-3.0, total_line=56.0)
        self.assertAlmostEqual(p["spread"]["home"] + p["spread"]["away"] + p["spread"]["push"], 1.0)
        self.assertAlmostEqual(p["total"]["over"] + p["total"]["under"] + p["total"]["push"], 1.0)
        self.assertEqual(p["moneyline"]["tie_unresolved"], 0.0)

    def test_key_number_and_calibration_readouts(self):
        h, a = simulate_cfb_v2_paths(self.model, self.rows[2], seed=9, n_paths=3000)
        mass = key_number_mass(h, a)
        self.assertEqual(set(mass), {3, 7, 10, 14})
        seen_n_paths = []

        def simulate(r, s, n_paths):
            seen_n_paths.append(n_paths)
            return simulate_cfb_v2_paths(self.model, r, seed=s, n_paths=n_paths)

        cal = outcome_calibration(simulate, self.rows[:40], n_paths=500)
        self.assertEqual(cal["n"], 40)
        self.assertEqual(seen_n_paths, [500] * 40)
        for key in ("margin", "total"):
            self.assertLessEqual(cal[key]["cover_50"], cal[key]["cover_80"])
            self.assertLessEqual(cal[key]["cover_80"], cal[key]["cover_95"])


if __name__ == "__main__":
    unittest.main()
