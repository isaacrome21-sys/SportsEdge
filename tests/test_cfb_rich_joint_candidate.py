from __future__ import annotations

import unittest

from sportsedge.research.cfb_rich_joint_candidate import (
    CFBRichCandidateError,
    fit_cfb_rich_joint_score_model,
)


BASE = {
    "off_ppa_rush": 0.1,
    "off_ppa_dropback": 0.2,
    "def_ppa_rush_allowed": 0.0,
    "def_ppa_dropback_allowed": 0.1,
    "off_success_rate": 0.45,
    "def_success_rate_allowed": 0.42,
    "standard_down_ppa": 0.12,
    "passing_down_success_rate": 0.35,
    "eckel_rate": 0.18,
    "points_per_eckel": 4.2,
    "points_per_drive": 2.4,
    "net_field_position": 2.0,
    "explosive_rate": 0.12,
}
RICH = {
    "returning_production": 0.65,
    "talent_composite": 700.0,
    "recruiting_3yr_points": 800.0,
    "portal_net_value": 0.1,
    "qb_value": 0.2,
    "qb_continuity": 1.0,
    "availability_value": 0.95,
    "coach_continuity": 1.0,
    "tempo_plays_per_game": 70.0,
    "havoc_created": 0.18,
    "havoc_allowed": 0.15,
    "special_teams_value": 0.05,
}


def _row(i: int):
    season = 2022 + (i // 25)
    return {
        "season": season,
        "game_start_ts": f"{season}-09-02T18:00:00+00:00",
        "feature_asof_ts": f"{season}-09-02T12:00:00+00:00",
        "source_asof_ts": {
            "advanced": f"{season}-09-02T11:00:00+00:00",
            "roster": f"{season}-09-01T18:00:00+00:00",
        },
        "home_metrics": {**BASE, "off_ppa_rush": BASE["off_ppa_rush"] + (i % 7) * 0.01},
        "away_metrics": {**BASE, "off_ppa_dropback": BASE["off_ppa_dropback"] + (i % 5) * 0.01},
        "home_context": {**RICH, "qb_value": RICH["qb_value"] + (i % 3) * 0.02},
        "away_context": {**RICH, "talent_composite": RICH["talent_composite"] - (i % 11)},
        "home_rest_days": 7,
        "away_rest_days": 7,
        "home_travel_miles": 0,
        "away_travel_miles": 400 + i,
        "home_timezone_shift": 0,
        "away_timezone_shift": 1,
        "neutral_site": False,
        "weather": {"game_indoor": False, "wind_speed": 7.0, "temperature": 72.0, "precip_probability": 0.1},
        "home_score": 24 + (i % 14),
        "away_score": 17 + (i % 10),
    }


class CFBRichJointCandidateTests(unittest.TestCase):
    def test_fit_uses_rich_pit_contract(self):
        rows = [_row(i) for i in range(100)]
        model = fit_cfb_rich_joint_score_model(rows)
        self.assertEqual(model.train_seasons, (2022, 2023, 2024, 2025))
        self.assertIn("qb_value_diff", model.feature_names)
        self.assertIn("returning_production_diff", model.feature_names)
        self.assertIn("havoc_created_diff", model.feature_names)
        home, away = model.predict_means(_row(101))
        self.assertGreaterEqual(home, 0.0)
        self.assertGreaterEqual(away, 0.0)

    def test_rejects_post_kickoff_feature(self):
        rows = [_row(i) for i in range(100)]
        rows[0]["feature_asof_ts"] = rows[0]["game_start_ts"]
        with self.assertRaisesRegex(CFBRichCandidateError, "STRICTLY_PREGAME"):
            fit_cfb_rich_joint_score_model(rows)

    def test_rejects_market_data_in_model_features(self):
        rows = [_row(i) for i in range(100)]
        rows[0]["home_context"]["spread_line"] = -3.5
        with self.assertRaisesRegex(CFBRichCandidateError, "MARKET_DATA_PROHIBITED"):
            fit_cfb_rich_joint_score_model(rows)

    def test_rejects_source_newer_than_feature_snapshot(self):
        rows = [_row(i) for i in range(100)]
        rows[0]["source_asof_ts"]["roster"] = f"{rows[0]['season']}-09-02T13:00:00+00:00"
        with self.assertRaisesRegex(CFBRichCandidateError, "SOURCE_AFTER_FEATURE_ASOF"):
            fit_cfb_rich_joint_score_model(rows)


if __name__ == "__main__":
    unittest.main()
