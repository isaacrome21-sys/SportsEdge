import copy
import unittest

import numpy as np

from sportsedge.sports.nfl.m2 import build_nfl_m2_features
from sportsedge.sports.nfl.m2_v2d_candidate import (
    derive_nfl_m2_v2d_score_distribution,
    fit_nfl_m2_v2d_candidate,
)


class NFLM2V2DStructuredMeanTests(unittest.TestCase):
    def _features(self, season, index, side, strength):
        sign = 1.0 if side == "home" else -1.0
        return build_nfl_m2_features({
            "off_epa": 0.08 + strength,
            "def_epa": -0.03 - 0.2 * strength,
            "pass_epa": 0.11 + 0.7 * strength,
            "rush_epa": 0.02 + 0.35 * strength,
            "opp_off_epa": 0.03 - 0.1 * strength,
            "opp_def_epa": -0.01 + 0.05 * strength,
            "pressure_for": 0.27 + 0.02 * sign + 0.04 * strength,
            "pressure_allowed": 0.25 - 0.02 * sign - 0.03 * strength,
            "success_rate": 0.43 + 0.06 * strength,
            "explosive_rate": 0.10 + 0.03 * strength,
            "rest_diff_days": sign,
            "travel_miles": 250.0 if side == "home" else 800.0,
            "timezone_crossings": 0.0 if side == "home" else 1.0,
            "short_week": 0.0,
            "bye_week": 0.0,
            "wind_mph": 7.0 + index,
            "roof_closed": 0.0,
            "qb_id": f"{side}_{season}_{index}",
            "qb_adjustment": 1.2 * strength,
            "prior_efficiency": 0.5 * strength,
            "prior_weight": 0.65,
            "feature_asof_ts": f"{season}-09-{9 + index:02d}T17:00:00+00:00",
            "game_start_ts": f"{season}-09-{10 + index:02d}T17:00:00+00:00",
        })

    def _rows(self):
        scores = ((24, 20), (27, 17), (20, 23), (31, 24), (17, 14), (28, 30))
        rows = []
        for season in (2020, 2021, 2022):
            for index in range(6):
                rows.append({
                    "game_id": f"{season}_{index}",
                    "season": season,
                    "home_features": self._features(season, index, "home", 0.02 * (index + 1)),
                    "away_features": self._features(season, index, "away", -0.015 * (index + 1)),
                    "home_score": scores[(season + index) % len(scores)][0],
                    "away_score": scores[(season + index) % len(scores)][1],
                })
        return rows

    def test_swap_structure_is_exact(self):
        rows = self._rows()
        model = fit_nfl_m2_v2d_candidate(rows, ridge_alpha=2.0)
        row = copy.deepcopy(rows[-1])
        swapped = copy.deepcopy(row)
        swapped["home_features"], swapped["away_features"] = row["away_features"], row["home_features"]
        margin, total = model.predict(row)
        swapped_margin, swapped_total = model.predict(swapped)
        self.assertAlmostEqual(total, swapped_total, places=12)

        coefficients = np.asarray(model.mean_model.margin_coefficients, dtype=float)
        means = np.asarray(model.mean_model.diff_means, dtype=float)
        scales = np.asarray(model.mean_model.diff_scales, dtype=float)
        symmetry_center = float(coefficients[0] - ((means / scales) @ coefficients[1:]))
        self.assertAlmostEqual(margin + swapped_margin, 2.0 * symmetry_center, places=12)

    def test_root_market_fields_cannot_change_fit_or_distribution(self):
        rows = self._rows()
        baseline = fit_nfl_m2_v2d_candidate(rows, ridge_alpha=2.0)
        contaminated = copy.deepcopy(rows)
        for row in contaminated:
            row.update({
                "spread_line": 99.5,
                "total_line": 999.5,
                "home_spread_odds": -10000,
                "away_spread_odds": 5000,
                "book": "PROHIBITED_SELECTOR_INPUT",
            })
        changed = fit_nfl_m2_v2d_candidate(contaminated, ridge_alpha=2.0)
        self.assertEqual(baseline, changed)
        self.assertEqual(
            derive_nfl_m2_v2d_score_distribution(baseline, rows[-1]),
            derive_nfl_m2_v2d_score_distribution(changed, contaminated[-1]),
        )

    def test_distribution_is_normalized_observed_integer_support(self):
        rows = self._rows()
        model = fit_nfl_m2_v2d_candidate(rows, ridge_alpha=2.0)
        distribution = derive_nfl_m2_v2d_score_distribution(model, rows[-1])
        observed = {(row["home_score"], row["away_score"]) for row in rows}
        self.assertAlmostEqual(sum(float(row["weight"]) for row in distribution), 1.0, places=12)
        for row in distribution:
            self.assertIn((row["home_score"], row["away_score"]), observed)
            self.assertEqual(row["margin"], row["home_score"] - row["away_score"])
            self.assertEqual(row["total"], row["home_score"] + row["away_score"])


if __name__ == "__main__":
    unittest.main()
