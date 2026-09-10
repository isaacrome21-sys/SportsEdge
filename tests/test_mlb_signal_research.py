from __future__ import annotations

import unittest

from sportsedge.sports.mlb.signal_research import (
    FEATURE_FAMILIES,
    MLBSignalResearchError,
    build_feature_rows,
    evaluate_predeclared_families,
    validate_research_seasons,
)


class MLBSignalResearchTests(unittest.TestCase):
    def test_exact_pre2025_window_is_required(self):
        self.assertEqual(validate_research_seasons([2021, 2022, 2023, 2024]), (2021, 2022, 2023, 2024))
        with self.assertRaisesRegex(MLBSignalResearchError, "SACRED_2025_HOLDOUT_FORBIDDEN"):
            validate_research_seasons([2021, 2022, 2023, 2024, 2025])
        with self.assertRaisesRegex(MLBSignalResearchError, "REQUIRES_EXACT_2021_2024_WINDOW"):
            validate_research_seasons([2021, 2022, 2023])

    def test_same_date_doubleheader_cannot_see_earlier_same_date_result(self):
        games = []
        game_pk = 1
        for day in range(1, 21):
            games.append({
                "game_pk": game_pk,
                "date": f"2021-04-{day:02d}",
                "home_id": 1,
                "away_id": 2,
                "home_score": 4 + (day % 3),
                "away_score": 2 + (day % 2),
            })
            game_pk += 1
        # Both games must be emitted from the identical prior-date snapshot.
        games.extend([
            {
                "game_pk": game_pk,
                "date": "2021-04-21",
                "home_id": 1,
                "away_id": 2,
                "home_score": 20,
                "away_score": 0,
            },
            {
                "game_pk": game_pk + 1,
                "date": "2021-04-21",
                "home_id": 1,
                "away_id": 2,
                "home_score": 0,
                "away_score": 20,
            },
        ])
        families = build_feature_rows(games)
        for rows in families.values():
            same_day = [row for row in rows if row["date"] == "2021-04-21"]
            self.assertEqual(len(same_day), 2)
            self.assertEqual(same_day[0]["features"], same_day[1]["features"])

    def test_2024_confirmation_only_reveals_baseline_and_2023_winner(self):
        feature_rows = {}
        for family, names in FEATURE_FAMILIES.items():
            rows = []
            game_pk = 1
            for season in (2021, 2022, 2023, 2024):
                for index in range(60):
                    rows.append({
                        "date": f"{season}-06-{(index % 28) + 1:02d}",
                        "season": season,
                        "game_pk": game_pk,
                        "features": [0.0] * len(names),
                        "margin": float((index % 9) - 4),
                        "total": float(6 + (index % 7)),
                    })
                    game_pk += 1
            feature_rows[family] = rows
        result = evaluate_predeclared_families(feature_rows)
        winner = result["selected_family"]
        self.assertIn(winner, FEATURE_FAMILIES)
        expected = {"baseline_v1"} if winner == "baseline_v1" else {"baseline_v1", winner}
        self.assertEqual(set(result["confirmation_2024"]), expected)
        self.assertFalse(result["selection_policy"]["sacred_2025_holdout_accessed"])
        self.assertFalse(result["promotion_evidence"])
        self.assertFalse(result["market_data_used"])


if __name__ == "__main__":
    unittest.main()
