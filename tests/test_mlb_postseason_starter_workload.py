import unittest

from scripts.audit_mlb_postseason_starter_workload import (
    completed_postseason_games, extract_actual_starters, grade_starter,
    season_regular_starts, FROZEN_SEASONS,
)


class PostseasonStarterWorkloadTest(unittest.TestCase):
    def test_only_completed_postseason_games(self):
        payload={"dates":[{"date":"2025-10-03","games":[
            {"gamePk":301,"gameType":"D","officialDate":"2025-10-03","status":{"abstractGameState":"Final"}},
            {"gamePk":302,"gameType":"R","officialDate":"2025-10-03","status":{"abstractGameState":"Final"}},
            {"gamePk":303,"gameType":"L","officialDate":"2025-10-03","status":{"abstractGameState":"Preview"}}]}]}
        games=completed_postseason_games(payload,2025)
        self.assertEqual([g["game_pk"] for g in games],[301])

    def test_identifies_actual_boxscore_starters_and_baseball_outs(self):
        payload={"liveData":{"boxscore":{"teams":{
            "away":{"pitchers":[101,102],"players":{"ID101":{"stats":{"pitching":{
                "inningsPitched":"4.1","strikeOuts":3}}}}},
            "home":{"pitchers":[201],"players":{"ID201":{"stats":{"pitching":{
                "inningsPitched":"5.2","strikeOuts":5}}}}}
        }}}}
        actual=extract_actual_starters(payload,{"game_pk":301,"date":"2025-10-03","game_type":"D"})
        self.assertEqual([x["outs"] for x in actual],[13,17])
        self.assertEqual([x["player_id"] for x in actual],[101,201])

    def test_low_history_kept_explicitly_non_evaluable(self):
        recent=[{"date":f"2025-09-{i:02d}","row":{"outs":18,"strikeouts":5,
                   "earned_runs":0,"hits_allowed":2,"walks_allowed":1}} for i in range(1,5)]
        candidate={"game_pk":301,"date":"2025-10-03","game_type":"D",
                   "player_id":101,"team_side":"away","outs":13,"strikeouts":3}
        scored=grade_starter(candidate,recent)
        self.assertEqual(scored["status"],"INSUFFICIENT_PRIOR_REGULAR_STARTS")
        self.assertFalse(scored["records"])

    def test_no_game_day_or_later_regular_history_leaks(self):
        game={"game_pk":301,"date":"2025-10-03","game_type":"D",
              "player_id":101,"team_side":"away","outs":13,"strikeouts":3}
        invalid=[{"date":"2025-10-03","row":{"outs":12,"strikeouts":2,
                 "earned_runs":2,"hits_allowed":3,"walks_allowed":0}}]
        with self.assertRaises(ValueError):
            grade_starter(game, invalid)

    def test_seasons_frozen(self):
        self.assertEqual(FROZEN_SEASONS,(2023,2024,2025))


if __name__ == "__main__":
    unittest.main()
