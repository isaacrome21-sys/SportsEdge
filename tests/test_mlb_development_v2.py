from __future__ import annotations

import unittest

import numpy as np

from scripts.fit_mlb_development_v2 import (
    CONTEXT_FEATURE_NAMES,
    MLBDevelopmentV2Error,
    build_context_extras,
    build_v2_feature_sets,
    fetch_season_with_venue,
)


class MLBDevelopmentV2Tests(unittest.TestCase):
    @staticmethod
    def _games() -> list[dict]:
        games: list[dict] = []
        game_pk = 1000
        # Two clubs play enough prior games to make the feature rows usable.
        for index in range(24):
            month = 4 if index < 20 else 5
            day = index + 1 if month == 4 else index - 19
            games.append({
                "game_pk": game_pk,
                "date": f"2023-{month:02d}-{day:02d}",
                "home_id": 1 if index % 2 == 0 else 2,
                "away_id": 2 if index % 2 == 0 else 1,
                "home_score": 3 + (index % 5),
                "away_score": 2 + ((index * 2) % 4),
                "venue_id": 10 if index % 2 == 0 else 20,
            })
            game_pk += 1
        return games

    def test_http_guard_rejects_2025_before_request(self) -> None:
        with self.assertRaisesRegex(MLBDevelopmentV2Error, "POST_2024_HTTP_FORBIDDEN"):
            fetch_season_with_venue(2025, retries=1)

    def test_context_rows_share_exact_identity_with_existing_feature_sets(self) -> None:
        games = self._games()
        feature_sets, margin, total, dates, game_pks = build_v2_feature_sets(games)
        self.assertEqual(set(feature_sets), {"baseline_v1", "pit_multiwindow_v1", "pit_context_v2"})
        self.assertEqual(len(dates), len(game_pks))
        self.assertEqual(len(dates), len(margin))
        self.assertEqual(len(dates), len(total))
        for matrix, names in feature_sets.values():
            self.assertEqual(len(matrix), len(dates))
            self.assertEqual(matrix.shape[1], len(names))
            self.assertTrue(np.isfinite(matrix).all())
        self.assertEqual(
            feature_sets["pit_context_v2"][0].shape[1],
            feature_sets["pit_multiwindow_v1"][0].shape[1] + len(CONTEXT_FEATURE_NAMES),
        )

    def test_same_date_games_use_identical_prior_context_snapshot(self) -> None:
        games = self._games()
        # Add a same-date doubleheader after the 20-game minimum is satisfied.
        games.extend([
            {
                "game_pk": 2001, "date": "2023-05-06", "home_id": 1, "away_id": 2,
                "home_score": 20, "away_score": 0, "venue_id": 10,
            },
            {
                "game_pk": 2002, "date": "2023-05-06", "home_id": 1, "away_id": 2,
                "home_score": 0, "away_score": 20, "venue_id": 10,
            },
        ])
        extras, names, dates, game_pks = build_context_extras(games)
        self.assertEqual(len(names), len(CONTEXT_FEATURE_NAMES))
        indices = [index for index, value in enumerate(dates) if value == "2023-05-06"]
        self.assertEqual(len(indices), 2)
        np.testing.assert_allclose(extras[indices[0]], extras[indices[1]], rtol=0, atol=0)
        self.assertEqual({game_pks[index] for index in indices}, {2001, 2002})


if __name__ == "__main__":
    unittest.main()
