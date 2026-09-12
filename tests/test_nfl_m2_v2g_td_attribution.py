import unittest

from sportsedge.sports.nfl.m2_v2g_candidate import build_nfl_v2g_game_event_rows


class NFLV2GTouchdownAttributionTests(unittest.TestCase):
    def test_defensive_touchdown_is_not_credited_to_possession_offense(self):
        schedule = [{
            "game_id": "2026_01_A_B",
            "game_type": "REG",
            "season": 2026,
            "week": 1,
            "home_team": "A",
            "away_team": "B",
        }]
        pbp = [
            {
                "game_id": "2026_01_A_B",
                "posteam": "A",
                "drive": 1,
                "touchdown": 1,
                "td_team": "B",
                "play_type": "run",
            },
            {
                "game_id": "2026_01_A_B",
                "posteam": "B",
                "drive": 2,
                "touchdown": 0,
                "td_team": None,
                "play_type": "run",
            },
        ]

        rows = build_nfl_v2g_game_event_rows(schedule, pbp)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["home_touchdowns"], 0)
        self.assertEqual(rows[0]["home_other_no_score"], 1)
        self.assertEqual(rows[0]["away_touchdowns"], 0)
        self.assertEqual(rows[0]["away_other_no_score"], 1)

    def test_offensive_touchdown_requires_scoring_team_to_match_possession_team(self):
        schedule = [{
            "game_id": "2026_01_A_B",
            "game_type": "REG",
            "season": 2026,
            "week": 1,
            "home_team": "A",
            "away_team": "B",
        }]
        pbp = [
            {
                "game_id": "2026_01_A_B",
                "posteam": "A",
                "drive": 1,
                "touchdown": 1,
                "td_team": "A",
                "play_type": "pass",
            },
            {
                "game_id": "2026_01_A_B",
                "posteam": "B",
                "drive": 2,
                "touchdown": 0,
                "td_team": None,
                "play_type": "run",
            },
        ]

        rows = build_nfl_v2g_game_event_rows(schedule, pbp)
        self.assertEqual(rows[0]["home_touchdowns"], 1)
        self.assertEqual(rows[0]["home_other_no_score"], 0)


if __name__ == "__main__":
    unittest.main()
