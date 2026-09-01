from __future__ import annotations

from datetime import datetime, timezone
import unittest

from sportsedge.sports.cfb.historical_features import CFBHistoricalFeatureError, materialize_cfb_joint_history
from sportsedge.sports.cfb.source import CFBTeamMetrics

UTC=timezone.utc
FBS={2025:[{"school":"Alpha State"},{"school":"Beta Tech"}],2026:[{"school":"Alpha State"},{"school":"Beta Tech"}]}
WEATHER={"w1":{"game_indoor":True},"w2":{"game_indoor":False,"wind_speed":5.0,"temperature":72.0}}


def metric(team, *, season, through_week, source, asof):
    return CFBTeamMetrics(
        team=team,season=season,through_week=through_week,sample_source=source,
        off_ppa_rush=.1,off_ppa_dropback=.2,def_ppa_rush_allowed=.05,def_ppa_dropback_allowed=.08,
        off_success_rate=.45,def_success_rate_allowed=.42,standard_down_ppa=.12,
        passing_down_success_rate=.39,eckel_rate=.3,points_per_eckel=4.5,points_per_drive=2.2,
        net_field_position=1.0,explosive_rate=.1,feature_asof_ts=asof,
    )


def game(gid,week,start):
    return {"game_id":gid,"season":2026,"week":week,"start_ts":start,"home_team":"Alpha State","away_team":"Beta Tech","neutral_site":False,"home_score":27,"away_score":20}


class CFBHistoricalMaterializerTests(unittest.TestCase):
    def test_week1_prior_season_and_week2_prior_week_are_selected_exactly(self):
        metrics=[
            metric("Alpha State",season=2025,through_week=99,source="PRIOR_SEASON_FALLBACK",asof="2026-08-01T00:00:00+00:00"),
            metric("Beta Tech",season=2025,through_week=99,source="PRIOR_SEASON_FALLBACK",asof="2026-08-01T00:00:00+00:00"),
            metric("Alpha State",season=2026,through_week=1,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-05T00:00:00+00:00"),
            metric("Beta Tech",season=2026,through_week=1,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-05T00:00:00+00:00"),
            # Target-week rows may exist in the frozen store but must never be selected for Week 2.
            metric("Alpha State",season=2026,through_week=2,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-12T00:00:00+00:00"),
            metric("Beta Tech",season=2026,through_week=2,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-12T00:00:00+00:00"),
        ]
        rows=materialize_cfb_joint_history(
            games=[game("w1",1,"2026-08-29T16:00:00+00:00"),game("w2",2,"2026-09-12T19:30:00+00:00")],
            metrics=metrics,weather_by_game=WEATHER,fbs_membership_by_season=FBS,
        )
        self.assertEqual([r["game_id"] for r in rows],["w1","w2"])
        self.assertEqual(rows[0]["home_metrics"]["season"],2025)
        self.assertEqual(rows[0]["home_metrics"]["sample_source"],"PRIOR_SEASON_FALLBACK")
        self.assertEqual(rows[1]["home_metrics"]["through_week"],1)
        self.assertEqual(rows[1]["away_metrics"]["through_week"],1)

    def test_week2_fails_if_only_target_week_metric_exists(self):
        metrics=[
            metric("Alpha State",season=2026,through_week=2,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-10T00:00:00+00:00"),
            metric("Beta Tech",season=2026,through_week=2,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-10T00:00:00+00:00"),
        ]
        with self.assertRaisesRegex(CFBHistoricalFeatureError,"CFB_HISTORICAL_PRIOR_WEEK_METRIC_MISSING:Alpha State:2026:1"):
            materialize_cfb_joint_history(games=[game("w2",2,"2026-09-12T19:30:00+00:00")],metrics=metrics,weather_by_game=WEATHER,fbs_membership_by_season=FBS)

    def test_post_kickoff_feature_snapshot_fails_closed(self):
        metrics=[
            metric("Alpha State",season=2026,through_week=1,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-12T20:00:00+00:00"),
            metric("Beta Tech",season=2026,through_week=1,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-05T00:00:00+00:00"),
        ]
        with self.assertRaisesRegex(CFBHistoricalFeatureError,"CFB_HISTORICAL_FEATURE_NOT_PREGAME:Alpha State"):
            materialize_cfb_joint_history(games=[game("w2",2,"2026-09-12T19:30:00+00:00")],metrics=metrics,weather_by_game=WEATHER,fbs_membership_by_season=FBS)

    def test_market_data_in_historical_game_row_is_rejected(self):
        bad=game("w2",2,"2026-09-12T19:30:00+00:00"); bad["closing_line"]=-3.5
        metrics=[
            metric("Alpha State",season=2026,through_week=1,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-05T00:00:00+00:00"),
            metric("Beta Tech",season=2026,through_week=1,source="CURRENT_SEASON_PRIOR_WEEKS",asof="2026-09-05T00:00:00+00:00"),
        ]
        with self.assertRaisesRegex(CFBHistoricalFeatureError,"CFB_HISTORICAL_MARKET_DATA_PROHIBITED:closing_line"):
            materialize_cfb_joint_history(games=[bad],metrics=metrics,weather_by_game=WEATHER,fbs_membership_by_season=FBS)


if __name__=="__main__": unittest.main()
