from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from scripts.fit_mlb_development_v3 import (
    MLBDevelopmentV3Error,
    STARTER_FEATURE_NAMES,
    build_starter_extras,
    build_v3_feature_sets,
    fetch_season_with_starters,
)


class MLBDevelopmentV3Tests(unittest.TestCase):
    @staticmethod
    def _games() -> list[dict]:
        games: list[dict] = []
        for index in range(26):
            month = 4 if index < 20 else 5
            day = index + 1 if index < 20 else index - 19
            games.append({
                "game_pk": 5000 + index,
                "date": f"2023-{month:02d}-{day:02d}",
                "home_id": 1 if index % 2 == 0 else 2,
                "away_id": 2 if index % 2 == 0 else 1,
                "home_score": 3 + (index % 4),
                "away_score": 2 + ((index * 2) % 5),
                "home_starter_id": 101 if index % 2 == 0 else 201,
                "away_starter_id": 201 if index % 2 == 0 else 101,
            })
        return games

    def test_2025_is_rejected_before_http(self) -> None:
        with patch("scripts.fit_mlb_development_v3.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(MLBDevelopmentV3Error, "POST_2024_HTTP_FORBIDDEN"):
                fetch_season_with_starters(2025, retries=1)
            urlopen.assert_not_called()

    def test_starter_features_share_v1_row_identity(self) -> None:
        feature_sets, margin, total, dates, game_pks, coverage = build_v3_feature_sets(self._games())
        self.assertEqual(set(feature_sets), {"baseline_v1", "pit_starter_v3"})
        self.assertGreater(len(dates), 0)
        self.assertEqual(len(dates), len(game_pks))
        self.assertEqual(len(dates), len(margin))
        self.assertEqual(len(dates), len(total))
        baseline, baseline_names = feature_sets["baseline_v1"]
        starter, starter_names = feature_sets["pit_starter_v3"]
        self.assertEqual(len(baseline), len(starter))
        self.assertEqual(starter.shape[1], len(baseline_names) + len(STARTER_FEATURE_NAMES))
        self.assertEqual(starter.shape[1], len(starter_names))
        self.assertTrue(np.isfinite(starter).all())
        self.assertEqual(coverage["usable_rows"], len(dates))

    def test_same_date_doubleheader_cannot_see_first_game_starter_outcome(self) -> None:
        games = self._games()
        games.extend([
            {
                "game_pk": 7001, "date": "2023-05-08", "home_id": 1, "away_id": 2,
                "home_score": 18, "away_score": 0, "home_starter_id": 101, "away_starter_id": 201,
            },
            {
                "game_pk": 7002, "date": "2023-05-08", "home_id": 1, "away_id": 2,
                "home_score": 0, "away_score": 18, "home_starter_id": 101, "away_starter_id": 201,
            },
        ])
        extras, names, dates, game_pks, _ = build_starter_extras(games)
        self.assertEqual(names, STARTER_FEATURE_NAMES)
        indices = [index for index, value in enumerate(dates) if value == "2023-05-08"]
        self.assertEqual(len(indices), 2)
        np.testing.assert_allclose(extras[indices[0]], extras[indices[1]], rtol=0, atol=0)
        self.assertEqual({game_pks[index] for index in indices}, {7001, 7002})

    def test_missing_starter_identity_is_neutral_and_explicit(self) -> None:
        games = self._games()
        games[-1]["home_starter_id"] = 0
        extras, names, dates, game_pks, coverage = build_starter_extras(games)
        index = game_pks.index(games[-1]["game_pk"])
        values = dict(zip(names, extras[index]))
        self.assertEqual(values["home_sp_ra5_delta_team_ra30_shrunk"], 0.0)
        self.assertEqual(values["home_sp_ra10_delta_team_ra30_shrunk"], 0.0)
        self.assertEqual(values["home_sp_prior_starts_cap10"], 0.0)
        self.assertEqual(values["home_sp_identity_available"], 0.0)
        self.assertLess(coverage["home_identity_available"], coverage["usable_rows"])


if __name__ == "__main__":
    unittest.main()
