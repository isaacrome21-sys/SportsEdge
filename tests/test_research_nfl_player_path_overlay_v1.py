from __future__ import annotations

import unittest

from sportsedge.sports.nfl.player_path_overlay_v1 import (
    NFLPlayerPathOverlayError,
    simulate_player_overlays_by_seed,
    simulate_player_stats_for_path,
)
from sportsedge.sports.nfl.sgp_joint_probability import joint_probability_from_paths
from sportsedge.sports.nfl.sgp_v2k_adapter import attach_player_stats_by_seed


def _drive(index: int, offense: str, outcome: str) -> dict:
    return {
        "drive_index": index,
        "offense": offense,
        "defense": "IND" if offense == "KC" else "KC",
        "outcome": outcome,
    }


def _path(
    seed: int,
    *,
    home_score: int = 31,
    away_score: int = 14,
    kc_td_drives: int = 1,
) -> dict:
    drives: list[dict] = []
    idx = 0
    for _ in range(kc_td_drives):
        drives.append(_drive(idx, "KC", "TD"))
        idx += 1
    drives.append(_drive(idx, "IND", "PUNT_OTHER"))
    idx += 1
    drives.append(_drive(idx, "KC", "PUNT_OTHER"))
    idx += 1
    drives.append(_drive(idx, "IND", "PUNT_OTHER"))
    return {
        "game_id": "IND@KC",
        "simulation_seed": seed,
        "home_team": "KC",
        "away_team": "IND",
        "home_score": home_score,
        "away_score": away_score,
        "drive_path": drives,
        "players": {},
    }


def _profiles() -> dict:
    return {
        "KC": {
            "plays_mean": 8.0,
            "plays_sd": 0.01,
            "pass_rate": 0.5,
            "targetable_pass_rate": 1.0,
            "expected_offensive_drives": 2.0,
            "players": {
                "Rashee Rice": {
                    "target_share": 1.0,
                    "catch_rate": 1.0,
                    "yards_per_reception": 10.0,
                    "yards_per_reception_sd": 0.01,
                    "rush_share": 0.0,
                    "yards_per_carry": 0.0,
                    "yards_per_carry_sd": 0.01,
                    "td_share": 1.0,
                }
            },
        },
        "IND": {
            "plays_mean": 4.0,
            "plays_sd": 0.01,
            "pass_rate": 0.0,
            "targetable_pass_rate": 1.0,
            "expected_offensive_drives": 2.0,
            "players": {
                "Tyler Warren": {
                    "target_share": 1.0,
                    "catch_rate": 1.0,
                    "yards_per_reception": 9.0,
                    "yards_per_reception_sd": 0.01,
                    "rush_share": 0.0,
                    "yards_per_carry": 0.0,
                    "yards_per_carry_sd": 0.01,
                    "td_share": 0.0,
                }
            },
        },
    }


class NFLPlayerPathOverlayV1Tests(unittest.TestCase):
    def test_market_inputs_are_rejected(self):
        profiles = _profiles()
        profiles["KC"]["line"] = -6
        with self.assertRaisesRegex(NFLPlayerPathOverlayError, "MARKET_INPUT_FORBIDDEN:line"):
            simulate_player_stats_for_path(_path(1), profiles)

    def test_same_seed_same_inputs_are_deterministic(self):
        path = _path(101, kc_td_drives=2)
        first = simulate_player_stats_for_path(path, _profiles())
        second = simulate_player_stats_for_path(path, _profiles())
        self.assertEqual(first, second)
        self.assertEqual(first["Rashee Rice"]["simulation_seed"], 101)
        self.assertEqual(first["Tyler Warren"]["simulation_seed"], 101)

    def test_touchdowns_follow_exact_simulated_team_td_count(self):
        with_two = simulate_player_stats_for_path(_path(7, kc_td_drives=2), _profiles())
        with_zero = simulate_player_stats_for_path(_path(8, kc_td_drives=0), _profiles())
        self.assertEqual(with_two["Rashee Rice"]["touchdowns"], 2)
        self.assertEqual(with_zero["Rashee Rice"]["touchdowns"], 0)

    def test_receptions_are_generated_from_same_path_volume(self):
        profiles = _profiles()
        profiles["IND"]["pass_rate"] = 1.0
        stats = simulate_player_stats_for_path(_path(55), profiles)
        warren = stats["Tyler Warren"]
        self.assertGreaterEqual(warren["targets"], 0)
        self.assertEqual(warren["receptions"], warren["targets"])
        self.assertGreaterEqual(warren["receiving_yards"], 0.0)
        self.assertEqual(warren["model_id"], "NFL_PLAYER_PATH_OVERLAY_V1")

    def test_role_shares_above_one_are_rejected(self):
        profiles = _profiles()
        profiles["KC"]["players"]["Travis Kelce"] = {
            "target_share": 0.25,
            "catch_rate": 0.7,
            "yards_per_reception": 10.0,
            "rush_share": 0.0,
            "yards_per_carry": 0.0,
            "td_share": 0.0,
        }
        with self.assertRaisesRegex(NFLPlayerPathOverlayError, "PLAYER_ROLE_SHARES_EXCEED_ONE"):
            simulate_player_stats_for_path(_path(9), profiles)

    def test_overlays_are_keyed_by_unique_simulation_seed(self):
        paths = [_path(11), _path(12)]
        overlays = simulate_player_overlays_by_seed(paths, _profiles())
        self.assertEqual(set(overlays), {11, 12})
        self.assertEqual(overlays[11]["Rashee Rice"]["simulation_seed"], 11)
        duplicate = [_path(11), _path(11)]
        with self.assertRaisesRegex(NFLPlayerPathOverlayError, "DUPLICATE_SIMULATION_SEED"):
            simulate_player_overlays_by_seed(duplicate, _profiles())

    def test_missing_team_profile_fails_closed(self):
        profiles = _profiles()
        del profiles["IND"]
        with self.assertRaisesRegex(NFLPlayerPathOverlayError, "TEAM_PROFILE_REQUIRED:IND"):
            simulate_player_stats_for_path(_path(13), profiles)

    def test_end_to_end_same_path_promo_probability(self):
        paths = [
            _path(21, home_score=31, away_score=14, kc_td_drives=1),
            _path(22, home_score=24, away_score=21, kc_td_drives=1),
        ]
        overlays = simulate_player_overlays_by_seed(paths, _profiles())
        joined = attach_player_stats_by_seed(paths, overlays)
        result = joint_probability_from_paths(
            joined,
            [
                {"game_id": "IND@KC", "market": "spread", "team": "KC", "line": -6},
                {
                    "game_id": "IND@KC",
                    "market": "anytime_td",
                    "player": "Rashee Rice",
                    "side": "YES",
                },
                {
                    "game_id": "IND@KC",
                    "market": "receptions",
                    "player": "Tyler Warren",
                    "side": "UNDER",
                    "line": 4.5,
                },
            ],
        )
        self.assertEqual(result["method"], "SAME_SIMULATION_PATHS")
        self.assertFalse(result["independence_assumption"])
        self.assertEqual(result["resolved_paths"], 2)
        self.assertEqual(result["full_win_paths"], 1)
        self.assertAlmostEqual(result["joint_model_probability"], 0.5)


if __name__ == "__main__":
    unittest.main()
