from __future__ import annotations

import unittest

from sportsedge.sports.cfb.historical_features import (
    CFBHistoricalFeatureError,
    build_week_to_date_metrics,
)


def schedule(week=1, game="1", home="10", away="20", hs=28, ass=21):
    return {
        "game_id": game,
        "season": "2024",
        "week": str(week),
        "status_type_completed": "TRUE",
        "home_id": home,
        "away_id": away,
        "home_location": "Alpha",
        "away_location": "Beta",
        "home_score": str(hs),
        "away_score": str(ass),
    }


def team(game, team, rush_epa, pass_epa, explosive=3):
    return {
        "game_id": game,
        "pos_team": team,
        "rushes": "20",
        "passes": "30",
        "scrimmage_plays": "50",
        "EPA_rushing_overall": str(rush_epa),
        "EPA_passing_overall": str(pass_epa),
        "EPA_explosive_rushing": str(explosive),
        "EPA_explosive_passing": str(explosive),
    }


def situ(game, team, success=25):
    return {
        "game_id": game,
        "pos_team": team,
        "EPA_success": str(success),
        "standard_downs": "35",
        "EPA_standard_down": "7.0",
        "passing_downs": "15",
        "EPA_success_passing_down": "6",
    }


def drives(game, team, fp, n=10):
    return {"game_id": game, "pos_team": team, "drives": str(n), "avg_field_position": str(fp)}


def pbp(game, team, home, away, drive, points=0, scoring=True):
    row = {
        "game_id": game,
        "start.pos_team.id": team,
        "drive.id": drive,
        "scoring_opp": "TRUE" if scoring else "FALSE",
        "homeTeamId": home,
        "awayTeamId": away,
        "lag_homeScore": "0",
        "homeScore": "0",
        "lag_awayScore": "0",
        "awayScore": "0",
    }
    if team == home:
        row["homeScore"] = str(points)
    else:
        row["awayScore"] = str(points)
    return row


class HistoricalFeatureTests(unittest.TestCase):
    def fixture(self):
        schedules = [schedule(1), schedule(2, game="2", hs=35, ass=14)]
        teams = [
            team("1", "10", 4, 9), team("1", "20", 2, 6),
            team("2", "10", 20, 30), team("2", "20", 10, 15),
        ]
        situational = [
            situ("1", "10", 25), situ("1", "20", 20),
            situ("2", "10", 50), situ("2", "20", 10),
        ]
        drive_rows = [
            drives("1", "10", 70), drives("1", "20", 75),
            drives("2", "10", 60), drives("2", "20", 80),
        ]
        plays = [
            pbp("1", "10", "10", "20", "a", 7),
            pbp("1", "20", "10", "20", "b", 3),
            pbp("2", "10", "10", "20", "c", 7),
            pbp("2", "20", "10", "20", "d", 0),
        ]
        return schedules, teams, situational, drive_rows, plays

    def test_week_two_uses_week_one_only(self):
        s, t, si, d, p = self.fixture()
        out = build_week_to_date_metrics(
            season=2024, through_week=2, schedules=s, adv_team=t,
            adv_situational=si, adv_drives=d, play_by_play=p,
            feature_asof_ts="2024-09-07T12:00:00Z",
        )
        a = out["Alpha"]
        self.assertAlmostEqual(a.off_ppa_rush, 4 / 20)
        self.assertAlmostEqual(a.off_ppa_dropback, 9 / 30)
        self.assertAlmostEqual(a.def_ppa_rush_allowed, 2 / 20)
        self.assertAlmostEqual(a.eckel_rate, .1)
        self.assertAlmostEqual(a.points_per_eckel, 7.0)
        self.assertAlmostEqual(a.points_per_drive, 2.8)
        self.assertAlmostEqual(a.net_field_position, 5.0)
        self.assertEqual(a.through_week, 1)

    def test_same_week_massive_values_cannot_change_snapshot(self):
        s, t, si, d, p = self.fixture()
        first = build_week_to_date_metrics(
            season=2024, through_week=2, schedules=s, adv_team=t,
            adv_situational=si, adv_drives=d, play_by_play=p,
            feature_asof_ts="2024-09-07T12:00:00Z",
        )
        for row in t:
            if row["game_id"] == "2":
                row["EPA_rushing_overall"] = "999999"
        second = build_week_to_date_metrics(
            season=2024, through_week=2, schedules=s, adv_team=t,
            adv_situational=si, adv_drives=d, play_by_play=p,
            feature_asof_ts="2024-09-07T12:00:00Z",
        )
        self.assertEqual(first, second)

    def test_future_and_incomplete_games_are_excluded(self):
        s, t, si, d, p = self.fixture()
        future = schedule(3, game="3")
        future["status_type_completed"] = "FALSE"
        s.append(future)
        out = build_week_to_date_metrics(
            season=2024, through_week=3, schedules=s, adv_team=t,
            adv_situational=si, adv_drives=d, play_by_play=p,
            feature_asof_ts="2024-09-14T12:00:00Z",
        )
        self.assertEqual(out["Alpha"].through_week, 2)

    def test_missing_paired_advanced_row_fails_closed(self):
        s, t, si, d, p = self.fixture()
        t = [x for x in t if not (x["game_id"] == "1" and x["pos_team"] == "20")]
        with self.assertRaisesRegex(CFBHistoricalFeatureError, "pair_missing"):
            build_week_to_date_metrics(
                season=2024, through_week=2, schedules=s, adv_team=t,
                adv_situational=si, adv_drives=d, play_by_play=p,
                feature_asof_ts="2024-09-07T12:00:00Z",
            )

    def test_missing_eckel_sample_fails_closed(self):
        s, t, si, d, p = self.fixture()
        p = [x for x in p if x["start.pos_team.id"] != "10"]
        with self.assertRaisesRegex(CFBHistoricalFeatureError, "ECKEL_SAMPLE_MISSING"):
            build_week_to_date_metrics(
                season=2024, through_week=2, schedules=s, adv_team=t,
                adv_situational=si, adv_drives=d, play_by_play=p,
                feature_asof_ts="2024-09-07T12:00:00Z",
            )

    def test_defensive_return_score_not_credited_to_offense(self):
        s, t, si, d, p = self.fixture()
        p.append({
            "game_id": "1", "start.pos_team.id": "10", "drive.id": "a",
            "scoring_opp": "TRUE", "homeTeamId": "10", "awayTeamId": "20",
            "lag_homeScore": "7", "homeScore": "7", "lag_awayScore": "3", "awayScore": "10",
        })
        out = build_week_to_date_metrics(
            season=2024, through_week=2, schedules=s, adv_team=t,
            adv_situational=si, adv_drives=d, play_by_play=p,
            feature_asof_ts="2024-09-07T12:00:00Z",
        )
        self.assertAlmostEqual(out["Alpha"].points_per_eckel, 7.0)


if __name__ == "__main__":
    unittest.main()
