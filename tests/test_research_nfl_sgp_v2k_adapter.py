from __future__ import annotations

import unittest

from sportsedge.sports.nfl.sgp_joint_probability import joint_probability_from_paths
from sportsedge.sports.nfl.sgp_v2k_adapter import (
    NFLV2KSGPAdapterError,
    attach_player_stats_by_seed,
    simulate_v2k_sgp_paths,
    simulation_result_to_sgp_path,
)
from sportsedge.sports.nfl.v2k_drive_core import (
    DRIVE_OUTCOMES,
    FIELD_BUCKETS,
    STATE_BUCKETS,
    HierarchicalStrength,
    SimulationResult,
)


def _zeros() -> dict[str, float]:
    return {key: 0.0 for key in DRIVE_OUTCOMES}


def _toy_model() -> HierarchicalStrength:
    baseline = {key: 0.0 for key in DRIVE_OUTCOMES}
    baseline["TD"] = 0.35
    baseline["FG"] = 0.20
    baseline["PUNT_OTHER"] = 0.45
    return HierarchicalStrength(
        league_baseline=baseline,
        offense_effect={},
        defense_effect={},
        shrinkage_weight={},
        state_effect={bucket: _zeros() for bucket in STATE_BUCKETS},
        field_effect={bucket: _zeros() for bucket in FIELD_BUCKETS},
        conversion_probabilities={0: 0.05, 1: 0.90, 2: 0.05},
        start_field_positions=(50.0,),
        regulation_drive_counts=(8,),
        exceptional_score_points=(),
    )


class NFLV2KSGPAdapterTests(unittest.TestCase):
    def test_simulation_result_conversion_preserves_joint_game_state(self):
        result = SimulationResult(
            home_score=31,
            away_score=14,
            margin=17,
            total=45,
            team_totals={"KC": 31, "IND": 14},
            path=({"drive_index": 0, "outcome": "TD"},),
        )
        row = simulation_result_to_sgp_path(
            result,
            game_id="IND@KC",
            home_team="KC",
            away_team="IND",
            seed=17,
        )
        self.assertEqual(row["simulation_seed"], 17)
        self.assertEqual(row["home_score"], 31)
        self.assertEqual(row["away_score"], 14)
        self.assertEqual(row["simulation_source"], "V2K_DRIVE_CORE")
        self.assertEqual(row["drive_path"][0]["outcome"], "TD")

    def test_v2k_generates_one_deterministic_path_per_unique_seed(self):
        paths = simulate_v2k_sgp_paths(
            _toy_model(),
            game_id="IND@KC",
            home_team="KC",
            away_team="IND",
            seeds=[101, 102, 103],
            regulation_drives=8,
        )
        self.assertEqual([row["simulation_seed"] for row in paths], [101, 102, 103])
        self.assertTrue(all(row["game_id"] == "IND@KC" for row in paths))
        self.assertTrue(all(row["home_team"] == "KC" for row in paths))
        self.assertTrue(all(row["away_team"] == "IND" for row in paths))

    def test_duplicate_seed_rejected(self):
        with self.assertRaisesRegex(NFLV2KSGPAdapterError, "DUPLICATE_SEED"):
            simulate_v2k_sgp_paths(
                _toy_model(),
                game_id="IND@KC",
                home_team="KC",
                away_team="IND",
                seeds=[7, 7],
                regulation_drives=8,
            )

    def test_player_overlay_must_match_same_seed(self):
        base = [
            {
                "game_id": "IND@KC",
                "simulation_seed": 1,
                "home_team": "KC",
                "away_team": "IND",
                "home_score": 31,
                "away_score": 14,
                "players": {},
            },
            {
                "game_id": "IND@KC",
                "simulation_seed": 2,
                "home_team": "KC",
                "away_team": "IND",
                "home_score": 24,
                "away_score": 21,
                "players": {},
            },
        ]
        overlays = {
            1: {
                "Rashee Rice": {"touchdowns": 1},
                "Tyler Warren": {"receptions": 4},
            },
            2: {
                "Rashee Rice": {"touchdowns": 0},
                "Tyler Warren": {"receptions": 5},
            },
        }
        paths = attach_player_stats_by_seed(base, overlays)
        self.assertEqual(paths[0]["player_overlay_status"], "SAME_SEED_ATTACHED")
        self.assertEqual(paths[0]["players"]["Rashee Rice"]["touchdowns"], 1)
        self.assertEqual(paths[1]["players"]["Rashee Rice"]["touchdowns"], 0)

    def test_missing_overlay_fails_closed_by_default(self):
        base = [
            {
                "game_id": "IND@KC",
                "simulation_seed": 9,
                "home_team": "KC",
                "away_team": "IND",
                "home_score": 31,
                "away_score": 14,
            }
        ]
        with self.assertRaisesRegex(NFLV2KSGPAdapterError, "PLAYER_OVERLAY_MISSING"):
            attach_player_stats_by_seed(base, {})

    def test_seed_overlay_feeds_joint_probability_engine(self):
        base = [
            {
                "game_id": "IND@KC",
                "simulation_seed": 1,
                "home_team": "KC",
                "away_team": "IND",
                "home_score": 31,
                "away_score": 14,
            },
            {
                "game_id": "IND@KC",
                "simulation_seed": 2,
                "home_team": "KC",
                "away_team": "IND",
                "home_score": 24,
                "away_score": 21,
            },
        ]
        overlays = {
            1: {
                "Rashee Rice": {"touchdowns": 1},
                "Tyler Warren": {"receptions": 4},
            },
            2: {
                "Rashee Rice": {"touchdowns": 0},
                "Tyler Warren": {"receptions": 5},
            },
        }
        paths = attach_player_stats_by_seed(base, overlays)
        result = joint_probability_from_paths(
            paths,
            [
                {"game_id": "IND@KC", "market": "spread", "team": "KC", "line": -6},
                {"game_id": "IND@KC", "market": "anytime_td", "player": "Rashee Rice", "side": "YES"},
                {"game_id": "IND@KC", "market": "receptions", "player": "Tyler Warren", "side": "UNDER", "line": 4.5},
            ],
        )
        self.assertEqual(result["full_win_paths"], 1)
        self.assertEqual(result["resolved_paths"], 2)
        self.assertAlmostEqual(result["joint_model_probability"], 0.5)


if __name__ == "__main__":
    unittest.main()
