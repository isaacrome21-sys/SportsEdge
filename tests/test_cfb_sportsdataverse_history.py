import pytest

from sportsedge.sports.cfb.sportsdataverse_history import (
    SportsDataverseHistoryError, attach_drive_time, build_team_snapshots, validate_dataset,
)


def _rows(week, game_id=1):
    team={"game_id":game_id,"season":2025,"week":week,"pos_team":10,
          "EPA_rushing_per_play":0.1*week,"EPA_passing_per_play":0.2*week,
          "EPA_explosive_rate":0.05*week}
    situ={"game_id":game_id,"season":2025,"week":week,"pos_team":10,
          "EPA_success_rate":0.4,"EPA_standard_down_per_play":0.15,
          "EPA_success_passing_down_rate":0.35}
    drive={"game_id":game_id,"season":2025,"pos_team":10,"avg_field_position":70.0-week}
    sched={"game_id":game_id,"season":2025,"week":week}
    return team,situ,drive,sched


def test_betting_dataset_and_market_columns_are_rejected():
    with pytest.raises(SportsDataverseHistoryError, match="PROHIBITED_DATASET"):
        validate_dataset("espn_cfb_betting", [{"season":2025}])
    with pytest.raises(SportsDataverseHistoryError, match="MARKET_COLUMN_PROHIBITED"):
        validate_dataset("espn_cfb_adv_team", [{"season":2025,"game_spread":-3.5}])


def test_2026_realized_rows_are_rejected():
    with pytest.raises(SportsDataverseHistoryError, match="2026_OUTCOME"):
        validate_dataset("espn_cfb_adv_team", [{"season":2026}])


def test_adv_drives_must_inherit_time_from_schedule():
    d={"game_id":44,"season":2025,"pos_team":10,"avg_field_position":70}
    assert attach_drive_time([d],[{"game_id":44,"season":2025,"week":3}])[0]["week"] == 3
    with pytest.raises(SportsDataverseHistoryError, match="DRIVE_TIME_MISSING"):
        attach_drive_time([d],[])


def test_target_week_is_excluded_and_aggregation_is_deterministic():
    r1=_rows(1,101); r2=_rows(2,102); r3=_rows(3,103)
    snap=build_team_snapshots(
        adv_team_rows=[r3[0],r1[0],r2[0]],
        adv_situational_rows=[r2[1],r3[1],r1[1]],
        adv_drive_rows=[r1[2],r3[2],r2[2]],
        schedule_rows=[r2[3],r1[3],r3[3]],
        target_season=2025,target_week=3,
    )
    assert len(snap)==1
    assert snap[0].games_in_sample==2
    assert snap[0].through_week==2
    assert snap[0].off_ppa_rush == pytest.approx(0.15)
    assert snap[0].off_ppa_dropback == pytest.approx(0.30)


def test_join_coverage_mismatch_fails_closed():
    t,s,d,sch=_rows(1,101)
    with pytest.raises(SportsDataverseHistoryError, match="JOIN_COVERAGE"):
        build_team_snapshots(
            adv_team_rows=[t],adv_situational_rows=[s],adv_drive_rows=[],
            schedule_rows=[sch],target_season=2025,target_week=2,
        )
