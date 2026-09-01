import unittest

from sportsedge.sports.nfl.m2_history_features import select_starting_qb
from sportsedge.sports.nfl.m2_history_policy import _project_starter_depth_rows


class NFLM2HistoryPolicyDepthProjectionTests(unittest.TestCase):
    def test_projection_keeps_only_rows_either_selector_branch_can_use(self):
        rows = [
            {"season": "2018", "club_code": "TB", "week": "1", "game_type": "REG", "depth_team": "1", "position": "QB", "gsis_id": "QB1"},
            {"season": "2018", "club_code": "TB", "week": "1", "game_type": "REG", "depth_team": "2", "position": "QB", "gsis_id": "QB2"},
            {"season": "2018", "club_code": "TB", "week": "1", "game_type": "REG", "depth_team": "1", "position": "WR", "gsis_id": "WR1"},
            {"team": "TB", "dt": "2025-09-01T12:00:00-04:00", "pos_abb": "QB", "pos_rank": "1", "gsis_id": "TSQB1"},
            {"team": "TB", "dt": "2025-09-01T12:00:00-04:00", "pos_abb": "QB", "pos_rank": "2", "gsis_id": "TSQB2"},
            {"team": "TB", "dt": "2025-09-01T12:00:00-04:00", "pos_abb": "WR", "pos_rank": "1", "gsis_id": "TSWR1"},
        ]
        projected = _project_starter_depth_rows(rows)
        self.assertEqual([row["gsis_id"] for row in projected], ["QB1", "TSQB1"])

    def test_weekly_selection_is_identical_before_and_after_projection(self):
        rows = [
            {"season": "2018", "club_code": "TB", "week": "1", "game_type": "REG", "depth_team": "1", "position": "QB", "gsis_id": "QB1"},
            {"season": "2018", "club_code": "TB", "week": "2", "game_type": "REG", "depth_team": "2", "position": "QB", "gsis_id": "QB2"},
            {"season": "2018", "club_code": "TB", "week": "2", "game_type": "REG", "depth_team": "1", "position": "WR", "gsis_id": "WR1"},
        ]
        kwargs = dict(team="TB", season=2018, week=2, game_start_ts="2018-09-16T13:00:00-04:00")
        self.assertEqual(select_starting_qb(rows, **kwargs), select_starting_qb(_project_starter_depth_rows(rows), **kwargs))

    def test_timestamped_selection_is_identical_before_and_after_projection(self):
        rows = [
            {"team": "TB", "dt": "2025-08-25T12:00:00-04:00", "pos_abb": "QB", "pos_rank": "1", "gsis_id": "OLD"},
            {"team": "TB", "dt": "2025-08-30T12:00:00-04:00", "pos_abb": "QB", "pos_rank": "1", "gsis_id": "NEW"},
            {"team": "TB", "dt": "2025-08-31T12:00:00-04:00", "pos_abb": "QB", "pos_rank": "2", "gsis_id": "BACKUP"},
            {"team": "TB", "dt": "2025-08-31T12:00:00-04:00", "pos_abb": "WR", "pos_rank": "1", "gsis_id": "WR1"},
        ]
        kwargs = dict(team="TB", season=2025, week=1, game_start_ts="2025-09-01T13:00:00-04:00")
        self.assertEqual(select_starting_qb(rows, **kwargs), "NEW")
        self.assertEqual(select_starting_qb(rows, **kwargs), select_starting_qb(_project_starter_depth_rows(rows), **kwargs))

    def test_present_but_blank_depth_team_does_not_fall_back_to_pos_rank(self):
        rows = [{
            "season": "2018",
            "club_code": "TB",
            "week": "1",
            "game_type": "REG",
            "depth_team": "",
            "pos_rank": "1",
            "position": "QB",
            "gsis_id": "SHOULD_DROP",
        }]
        self.assertEqual(_project_starter_depth_rows(rows), [])


if __name__ == "__main__":
    unittest.main()
