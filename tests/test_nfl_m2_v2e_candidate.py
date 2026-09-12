import copy
import unittest

from sportsedge.sports.nfl.m2 import build_nfl_m2_features
from sportsedge.sports.nfl.m2_v2e_candidate import (
    derive_nfl_m2_v2e_score_distribution,
    fit_nfl_m2_v2e_candidate,
)


class NFLM2V2ECrossfitSupportTests(unittest.TestCase):
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
        for season in range(2019, 2024):
            for index in range(6):
                home_score, away_score = scores[(season + index) % len(scores)]
                rows.append({
                    "game_id": f"{season}_{index}",
                    "season": season,
                    "home_features": self._features(season, index, "home", 0.02 * (index + 1)),
                    "away_features": self._features(season, index, "away", -0.015 * (index + 1)),
                    "home_score": home_score,
                    "away_score": away_score,
                })
        return rows

    def test_support_coordinates_are_strictly_prior_season(self):
        model = fit_nfl_m2_v2e_candidate(self._rows(), ridge_alpha=2.0)
        self.assertEqual(model.dropped_support_seasons, (2019,))
        self.assertTrue(model.support_points)
        for point in model.support_points:
            self.assertTrue(point.coordinate_train_seasons)
            self.assertLess(max(point.coordinate_train_seasons), point.support_season)
            self.assertNotIn(point.support_season, point.coordinate_train_seasons)

    def test_support_season_outcome_cannot_change_its_own_coordinates(self):
        rows = self._rows()
        baseline = fit_nfl_m2_v2e_candidate(rows, ridge_alpha=2.0)
        changed_rows = copy.deepcopy(rows)
        for row in changed_rows:
            if row["season"] == 2021:
                row["home_score"] = 60
                row["away_score"] = 3
        changed = fit_nfl_m2_v2e_candidate(changed_rows, ridge_alpha=2.0)

        base_points = [p for p in baseline.support_points if p.support_season == 2021]
        changed_points = [p for p in changed.support_points if p.support_season == 2021]
        self.assertEqual(len(base_points), len(changed_points))
        self.assertEqual(
            [(p.predicted_margin, p.predicted_total, p.coordinate_train_seasons) for p in base_points],
            [(p.predicted_margin, p.predicted_total, p.coordinate_train_seasons) for p in changed_points],
        )
        self.assertNotEqual(
            [(p.home_score, p.away_score) for p in base_points],
            [(p.home_score, p.away_score) for p in changed_points],
        )

    def test_root_market_fields_cannot_change_candidate(self):
        rows = self._rows()
        baseline = fit_nfl_m2_v2e_candidate(rows, ridge_alpha=2.0)
        contaminated = copy.deepcopy(rows)
        for row in contaminated:
            row.update({
                "spread_line": 99.5,
                "total_line": 999.5,
                "home_spread_odds": -10000,
                "away_spread_odds": 5000,
                "book": "PROHIBITED_MODEL_INPUT",
            })
        changed = fit_nfl_m2_v2e_candidate(contaminated, ridge_alpha=2.0)
        self.assertEqual(baseline, changed)

    def test_distribution_is_normalized_observed_integer_support(self):
        rows = self._rows()
        model = fit_nfl_m2_v2e_candidate(rows, ridge_alpha=2.0)
        distribution = derive_nfl_m2_v2e_score_distribution(model, rows[-1])
        observed = {
            (row["home_score"], row["away_score"])
            for row in rows
            if row["season"] not in model.dropped_support_seasons
        }
        self.assertAlmostEqual(sum(float(row["weight"]) for row in distribution), 1.0, places=12)
        for row in distribution:
            self.assertIn((row["home_score"], row["away_score"]), observed)
            self.assertEqual(row["margin"], row["home_score"] - row["away_score"])
            self.assertEqual(row["total"], row["home_score"] + row["away_score"])


if __name__ == "__main__":
    unittest.main()
