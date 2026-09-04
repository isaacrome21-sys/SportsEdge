from __future__ import annotations

import unittest

from sportsedge.research.nfl_m2_nonlinear_candidate import (
    NFLM2NonlinearCandidateError,
    derive_nfl_m2_nonlinear_distribution,
    fit_nfl_m2_nonlinear_candidate,
)
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT


def _features(i: int, side: str):
    sign = 1.0 if side == "home" else -1.0
    return {
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "qb_id": f"{side}-qb-{i % 5}",
        "feature_asof_ts": "2025-09-01T12:00:00+00:00",
        "adj_off_epa": 0.05 + sign * (i % 11) * 0.004,
        "adj_def_epa": -0.03 + sign * (i % 7) * 0.003,
        "pass_epa": 0.08 + sign * (i % 9) * 0.005,
        "rush_epa": 0.02 + sign * (i % 6) * 0.004,
        "pressure_for": 0.30 + sign * (i % 5) * 0.01,
        "pressure_allowed": 0.28 - sign * (i % 4) * 0.01,
        "success_rate": 0.44 + sign * (i % 5) * 0.005,
        "explosive_rate": 0.11 + sign * (i % 4) * 0.004,
        "rest_diff_days": float((i % 4) - 1),
        "travel_miles": float(100 + (i % 13) * 50),
        "timezone_crossings": float(i % 3),
        "short_week": float(i % 9 == 0),
        "bye_week": float(i % 17 == 0),
        "wind_mph": float(4 + i % 12),
        "roof_closed": float(i % 5 == 0),
        "qb_adjustment": sign * ((i % 8) - 3) * 0.03,
        "prior_efficiency": 0.02 + sign * (i % 10) * 0.004,
        "prior_weight": 0.35,
    }


def _row(i: int):
    nonlinear = ((i % 7) - 3) ** 2
    return {
        "season": 2022 + ((i // 50) % 4),
        "home_features": _features(i, "home"),
        "away_features": _features(i, "away"),
        "home_score": 20 + (i % 15) + nonlinear,
        "away_score": 17 + ((i * 3) % 13),
    }


class NFLM2NonlinearCandidateTests(unittest.TestCase):
    def test_fit_and_distribution(self):
        rows = [_row(i) for i in range(220)]
        model = fit_nfl_m2_nonlinear_candidate(rows)
        self.assertEqual(model.train_seasons, (2022, 2023, 2024, 2025))
        self.assertGreater(len(model.basis_feature_names), len(model.base_feature_names))
        margin, total = model.predict(_row(221))
        self.assertIsInstance(margin, float)
        self.assertIsInstance(total, float)
        distribution = derive_nfl_m2_nonlinear_distribution(model, _row(221))
        self.assertEqual(len(distribution), len(rows))
        self.assertTrue(all(row["home_score"] >= 0 and row["away_score"] >= 0 for row in distribution))

    def test_market_data_is_rejected(self):
        rows = [_row(i) for i in range(220)]
        rows[0]["home_features"]["spread"] = -3.5
        with self.assertRaisesRegex(ValueError, "MARKET_DATA_PROHIBITED"):
            fit_nfl_m2_nonlinear_candidate(rows)

    def test_small_training_set_fails_closed(self):
        with self.assertRaisesRegex(NFLM2NonlinearCandidateError, "INSUFFICIENT"):
            fit_nfl_m2_nonlinear_candidate([_row(i) for i in range(50)])


if __name__ == "__main__":
    unittest.main()
