import copy
import unittest

from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT
from sportsedge.sports.nfl.m2_history_features import (
    build_nfl_m2_history_rows,
    fit_nfl_prior_decay_curves,
    select_starting_qb,
)


class NFLM2HistoryFeatureTests(unittest.TestCase):
    def _schedule(self):
        rows = []
        for season in (2019, 2020, 2021, 2022):
            for week in (1, 2, 3):
                rows.append({
                    "game_id": f"{season}_{week:02d}_AWY_HME",
                    "season": season,
                    "game_type": "REG",
                    "week": week,
                    "gameday": f"{season}-09-{7 + week:02d}",
                    "gametime": "13:00",
                    "away_team": "AWY",
                    "home_team": "HME",
                    "away_score": 17 + week,
                    "home_score": 24 + week + (season - 2019),
                    "away_rest": 7,
                    "home_rest": 8,
                    "roof": "outdoors",
                    "wind": 9,
                    "location": "Home",
                    "spread_line": -3.5,
                    "away_spread_odds": -110,
                    "home_spread_odds": -110,
                    "total_line": 44.5,
                    "under_odds": -110,
                    "over_odds": -110,
                })
        return rows

    def _pbp(self):
        rows = []
        for game in self._schedule():
            season = game["season"]
            week = game["week"]
            gid = game["game_id"]
            strength = 0.02 * (season - 2019) + 0.01 * week
            rows.extend([
                {"game_id": gid, "play_id": 1, "posteam": "HME", "defteam": "AWY", "epa": 0.20 + strength,
                 "qb_epa": 0.22 + strength, "pass": 1, "rush": 0, "qb_dropback": 1,
                 "passer_player_id": f"H_QB_{season}", "yards_gained": 22},
                {"game_id": gid, "play_id": 2, "posteam": "HME", "defteam": "AWY", "epa": -0.05 + strength,
                 "pass": 0, "rush": 1, "qb_dropback": 0, "yards_gained": 4},
                {"game_id": gid, "play_id": 3, "posteam": "AWY", "defteam": "HME", "epa": 0.08 - strength,
                 "qb_epa": 0.07 - strength, "pass": 1, "rush": 0, "qb_dropback": 1,
                 "passer_player_id": f"A_QB_{season}", "yards_gained": 8},
                {"game_id": gid, "play_id": 4, "posteam": "AWY", "defteam": "HME", "epa": -0.10 - strength,
                 "pass": 0, "rush": 1, "qb_dropback": 0, "yards_gained": 2},
            ])
        return rows

    def _participation(self):
        rows = []
        for game in self._schedule():
            gid = game["game_id"]
            rows.extend([
                {"nflverse_game_id": gid, "play_id": 1, "was_pressure": False},
                {"nflverse_game_id": gid, "play_id": 3, "was_pressure": True},
            ])
        return rows

    def _depth(self):
        rows = []
        for season in (2019, 2020, 2021, 2022):
            for week in (1, 2, 3):
                rows.extend([
                    {"season": season, "club_code": "HME", "week": week, "game_type": "REG",
                     "depth_team": 1, "position": "QB", "depth_position": "QB", "gsis_id": f"H_QB_{season}"},
                    {"season": season, "club_code": "HME", "week": week, "game_type": "REG",
                     "depth_team": 2, "position": "QB", "depth_position": "QB", "gsis_id": f"H_BACKUP_{season}"},
                    {"season": season, "club_code": "AWY", "week": week, "game_type": "REG",
                     "depth_team": 1, "position": "QB", "depth_position": "QB", "gsis_id": f"A_QB_{season}"},
                ])
        return rows

    def _stadiums(self):
        return [
            {"team_fastr": "HME", "stadium": "HME00", "first_game_date": "2000-01-01", "last_game_date": "2030-01-01",
             "lat": 41.0, "lon": -87.0, "tz_offset": -6},
            {"team_fastr": "AWY", "stadium": "AW00", "first_game_date": "2000-01-01", "last_game_date": "2030-01-01",
             "lat": 40.0, "lon": -74.0, "tz_offset": -5},
        ]

    def test_weekly_depth_chart_selects_rank_one_qb_for_game_week(self):
        qb = select_starting_qb(
            self._depth(), team="HME", season=2021, week=2,
            game_start_ts="2021-09-09T13:00:00-04:00",
        )
        self.assertEqual(qb, "H_QB_2021")

    def test_timestamped_depth_chart_must_be_strictly_before_kickoff(self):
        rows = [
            {"dt": "2025-09-01T12:00:00Z", "team": "HME", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "EARLY"},
            {"dt": "2025-09-07T18:00:00Z", "team": "HME", "pos_abb": "QB", "pos_rank": 1, "gsis_id": "LATE"},
        ]
        qb = select_starting_qb(rows, team="HME", season=2025, week=1, game_start_ts="2025-09-07T17:00:00Z")
        self.assertEqual(qb, "EARLY")

    def test_prior_decay_for_test_season_is_unchanged_when_test_outcomes_change(self):
        schedule = self._schedule()
        pbp = self._pbp()
        baseline = fit_nfl_prior_decay_curves(schedule, pbp, min_train_seasons=2, weeks=(1, 2, 3))
        mutated = copy.deepcopy(pbp)
        for row in mutated:
            if row["game_id"].startswith("2022_"):
                row["epa"] = 99.0
                if "qb_epa" in row:
                    row["qb_epa"] = 99.0
        changed = fit_nfl_prior_decay_curves(schedule, mutated, min_train_seasons=2, weeks=(1, 2, 3))
        self.assertEqual(baseline[2022], changed[2022])

    def test_history_builder_uses_only_prior_games_for_current_game_features(self):
        schedule = self._schedule()
        curves = fit_nfl_prior_decay_curves(schedule, self._pbp(), min_train_seasons=2, weeks=(1, 2, 3))
        baseline = build_nfl_m2_history_rows(
            schedule, self._pbp(), self._participation(), self._depth(), self._stadiums(),
            prior_decay_curves=curves,
        )
        mutated_pbp = copy.deepcopy(self._pbp())
        target = "2022_02_AWY_HME"
        for row in mutated_pbp:
            if row["game_id"] == target:
                row["epa"] = 500.0
                row["yards_gained"] = 500
        changed = build_nfl_m2_history_rows(
            schedule, mutated_pbp, self._participation(), self._depth(), self._stadiums(),
            prior_decay_curves=curves,
        )
        left = next(row for row in baseline if row["game_id"] == target)
        right = next(row for row in changed if row["game_id"] == target)
        self.assertEqual(left["home_features"], right["home_features"])
        self.assertEqual(left["away_features"], right["away_features"])

    def test_history_builder_emits_full_production_feature_contract_and_keeps_market_data_outside_m2(self):
        schedule = self._schedule()
        curves = fit_nfl_prior_decay_curves(schedule, self._pbp(), min_train_seasons=2, weeks=(1, 2, 3))
        rows = build_nfl_m2_history_rows(
            schedule, self._pbp(), self._participation(), self._depth(), self._stadiums(),
            prior_decay_curves=curves,
        )
        row = next(row for row in rows if row["game_id"] == "2022_03_AWY_HME")
        self.assertEqual(row["home_features"]["feature_contract"], NFL_M2_FEATURE_CONTRACT)
        self.assertEqual(row["away_features"]["feature_contract"], NFL_M2_FEATURE_CONTRACT)
        self.assertEqual(row["home_features"]["qb_id"], "H_QB_2022")
        self.assertEqual(row["away_features"]["qb_id"], "A_QB_2022")
        self.assertNotIn("spread_line", row["home_features"])
        self.assertNotIn("total_line", row["away_features"])
        self.assertEqual(row["spread_line"], -3.5)
        self.assertEqual(row["total_line"], 44.5)
        self.assertGreater(row["away_features"]["travel_miles"], 0.0)
        self.assertEqual(row["away_features"]["timezone_crossings"], 1.0)

    def test_pressure_rate_uses_participation_join_not_sack_proxy(self):
        schedule = self._schedule()
        curves = fit_nfl_prior_decay_curves(schedule, self._pbp(), min_train_seasons=2, weeks=(1, 2, 3))
        rows = build_nfl_m2_history_rows(
            schedule, self._pbp(), self._participation(), self._depth(), self._stadiums(),
            prior_decay_curves=curves,
        )
        row = next(row for row in rows if row["game_id"] == "2022_02_AWY_HME")
        # In all completed prior games, HME offense is never pressured and HME
        # defense always pressures AWY on its tracked dropback.
        self.assertEqual(row["home_features"]["pressure_allowed"], 0.0)
        self.assertEqual(row["home_features"]["pressure_for"], 1.0)

    def test_neutral_site_without_explicit_venue_fails_closed(self):
        schedule = self._schedule()
        schedule[-1]["location"] = "Neutral"
        curves = fit_nfl_prior_decay_curves(schedule, self._pbp(), min_train_seasons=2, weeks=(1, 2, 3))
        with self.assertRaisesRegex(ValueError, "NFL_NEUTRAL_VENUE_UNRESOLVED"):
            build_nfl_m2_history_rows(
                schedule, self._pbp(), self._participation(), self._depth(), self._stadiums(),
                prior_decay_curves=curves,
            )


if __name__ == "__main__":
    unittest.main()
