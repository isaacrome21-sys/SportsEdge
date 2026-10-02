from __future__ import annotations

import pytest

from sportsedge.sports.cfb.sportsdataverse_pipeline import (
    materialize_training_rows,
    training_manifest,
)


def _history():
    schedules=[]
    team=[]
    situ=[]
    drives=[]
    weather=[]
    for season in range(2015,2026):
        for week in (1,2):
            gid=season*100+week
            schedules.append({
                "game_id":gid,
                "season":season,
                "week":week,
                "season_type":"regular",
                "fbs_game":True,
                "completed":True,
                "start_date":f"{season}-09-0{week}T17:00:00Z",
                "neutral_site": season==2016 and week==1,
                "venue_id":100,
                "home_id":1,
                "away_id":2,
                "home_points":24+week,
                "away_points":17+week,
            })
            for pos_team, rush, pas, success, field in (
                (1,.10,.20,.45,70.0),
                (2,.02,.08,.38,72.0),
            ):
                team.append({
                    "game_id":gid,"season":season,"week":week,"pos_team":pos_team,
                    "EPA_rushing_per_play":rush+.01*week,
                    "EPA_passing_per_play":pas+.01*week,
                    "EPA_explosive_rate":.10+.005*week,
                })
                situ.append({
                    "game_id":gid,"season":season,"week":week,"pos_team":pos_team,
                    "EPA_success_rate":success,
                    "EPA_standard_down_per_play":.12+.01*week,
                    "EPA_success_passing_down_rate":.34+.01*week,
                })
                drives.append({
                    "game_id":gid,"season":season,"pos_team":pos_team,
                    "avg_field_position":field-week,
                })
            if season>=2016:
                weather.append({
                    "game_id":gid,
                    "game_indoor":True,
                    "wind_speed":None,
                    "temperature":None,
                })
    return schedules,team,situ,drives,weather


def test_materializes_2016_2025_rows_with_2015_bootstrap_only():
    schedules,team,situ,drives,weather=_history()
    rows=materialize_training_rows(
        schedules=schedules,
        adv_team_rows=team,
        adv_situational_rows=situ,
        adv_drive_rows=drives,
        weather_rows=weather,
    )
    assert len(rows)==20
    assert {r["season"] for r in rows}==set(range(2016,2026))
    assert all(r["season"]!=2015 for r in rows)
    neutral=next(r for r in rows if r["season"]==2016 and r["week"]==1)
    assert neutral["neutral_site"] is True
    assert neutral["weather_status"]=="WEATHER_BOUND"
    assert neutral["home_points"]==25
    assert neutral["away_points"]==18

    manifest=training_manifest(rows)
    assert manifest["row_count"]==20
    assert manifest["training_window"]["source_start_season"]==2015
    assert manifest["training_window"]["first_candidate_row_season"]==2016
    assert manifest["seasons"]==list(range(2016,2026))
    assert manifest["governance"]["attempts_consumed"]==0
    assert manifest["governance"]["evaluation_performed"] is False


def test_materialization_fails_closed_when_weather_missing():
    schedules,team,situ,drives,weather=_history()
    weather=[r for r in weather if r["game_id"]!=201601]
    with pytest.raises(Exception,match="HISTORICAL_WEATHER_INCOMPLETE"):
        materialize_training_rows(
            schedules=schedules,
            adv_team_rows=team,
            adv_situational_rows=situ,
            adv_drive_rows=drives,
            weather_rows=weather,
        )
