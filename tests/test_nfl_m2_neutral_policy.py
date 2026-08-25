import unittest

from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows


class NFLM2NeutralPolicyTests(unittest.TestCase):
    def test_neutral_game_can_be_excluded_from_evaluation_but_still_update_future_state(self):
        schedule = [
            {"game_id": "2020_01_A_B", "season": 2020, "game_type": "REG", "week": 1,
             "gameday": "2020-09-10", "gametime": "13:00", "away_team": "A", "home_team": "B",
             "away_score": 10, "home_score": 20, "away_rest": 7, "home_rest": 7, "roof": "outdoors", "wind": 5, "location": "Home"},
            {"game_id": "2021_01_A_B", "season": 2021, "game_type": "REG", "week": 1,
             "gameday": "2021-09-10", "gametime": "13:00", "away_team": "A", "home_team": "B",
             "away_score": 13, "home_score": 17, "away_rest": 7, "home_rest": 7, "roof": "outdoors", "wind": 5, "location": "Neutral"},
            {"game_id": "2021_02_A_B", "season": 2021, "game_type": "REG", "week": 2,
             "gameday": "2021-09-17", "gametime": "13:00", "away_team": "A", "home_team": "B",
             "away_score": 14, "home_score": 21, "away_rest": 7, "home_rest": 7, "roof": "outdoors", "wind": 5, "location": "Home",
             "spread_line": 3.5, "home_spread_odds": -110, "away_spread_odds": -110,
             "total_line": 41.5, "over_odds": -110, "under_odds": -110},
        ]
        pbp = [
            {"game_id": "2020_01_A_B", "play_id": 1, "posteam": "B", "defteam": "A", "epa": 0.1, "pass": 1, "qb_dropback": 1, "passer_player_id": "QB_B", "qb_epa": 0.1, "yards_gained": 5},
            {"game_id": "2020_01_A_B", "play_id": 2, "posteam": "A", "defteam": "B", "epa": -0.1, "pass": 1, "qb_dropback": 1, "passer_player_id": "QB_A", "qb_epa": -0.1, "yards_gained": 4},
            {"game_id": "2021_01_A_B", "play_id": 1, "posteam": "B", "defteam": "A", "epa": 0.9, "pass": 1, "qb_dropback": 1, "passer_player_id": "QB_B", "qb_epa": 0.9, "yards_gained": 25},
            {"game_id": "2021_01_A_B", "play_id": 2, "posteam": "A", "defteam": "B", "epa": -0.5, "pass": 1, "qb_dropback": 1, "passer_player_id": "QB_A", "qb_epa": -0.5, "yards_gained": 1},
            {"game_id": "2021_02_A_B", "play_id": 1, "posteam": "B", "defteam": "A", "epa": 0.2, "pass": 1, "qb_dropback": 1, "passer_player_id": "QB_B", "qb_epa": 0.2, "yards_gained": 8},
            {"game_id": "2021_02_A_B", "play_id": 2, "posteam": "A", "defteam": "B", "epa": 0.0, "pass": 1, "qb_dropback": 1, "passer_player_id": "QB_A", "qb_epa": 0.0, "yards_gained": 3},
        ]
        participation = [
            {"nflverse_game_id": row["game_id"], "play_id": row["play_id"], "was_pressure": False}
            for row in pbp
        ]
        depth = [
            {"season": 2021, "club_code": team, "week": week, "game_type": "REG", "depth_team": 1,
             "position": "QB", "depth_position": "QB", "gsis_id": qb}
            for team, qb in (("A", "QB_A"), ("B", "QB_B")) for week in (1, 2)
        ]
        stadiums = [
            {"team_fastr": "A", "first_game_date": "2000-01-01", "last_game_date": "2030-01-01", "lat": 40, "lon": -75, "tz_offset": -5},
            {"team_fastr": "B", "first_game_date": "2000-01-01", "last_game_date": "2030-01-01", "lat": 41, "lon": -87, "tz_offset": -6},
        ]
        rows = build_nfl_m2_history_rows(
            schedule, pbp, participation, depth, stadiums,
            prior_decay_curves={2021: {1: 0.5, 2: 0.0}}, neutral_site_policy="exclude_from_evaluation",
        )
        self.assertEqual([row["game_id"] for row in rows], ["2021_02_A_B"])
        # The excluded neutral Week 1 game must still be in the prior state used
        # for Week 2, so B's current-season offensive EPA is 0.9 rather than 0.
        self.assertAlmostEqual(rows[0]["home_features"]["pass_epa"], 0.9)

    def test_unknown_neutral_policy_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "NFL_NEUTRAL_SITE_POLICY_INVALID"):
            build_nfl_m2_history_rows([], [], [], [], [], prior_decay_curves={}, neutral_site_policy="guess")


if __name__ == "__main__": unittest.main()
