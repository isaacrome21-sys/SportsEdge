from scripts.materialize_cfb_sportsdataverse_training import (
    _predictive_surface,
    _scope_complete_advanced_join_games,
    _unresolved_venue_bindings,
)
from sportsedge.sports.cfb.sportsdataverse_history import TeamSnapshot


def snap(team,season,through_week,games=2):
    return TeamSnapshot(
        team_id=team,season=season,through_week=through_week,games_in_sample=games,
        off_ppa_rush=.1,off_ppa_dropback=.2,off_success_rate=.4,
        def_ppa_rush_allowed=-.1,def_ppa_dropback_allowed=.05,
        def_success_rate_allowed=.3,standard_down_ppa=.15,
        passing_down_success_rate=.35,explosive_rate=.1,net_field_position=-70,
    )


def test_2015_is_support_only_and_2016_week0_is_scoreable_from_prior():
    games=[
        {"game_id":1,"season":2015,"week":2,"home_id":1,"away_id":2,"neutral_site":False},
        {"game_id":2,"season":2016,"week":0,"home_id":1,"away_id":2,"neutral_site":False},
    ]
    rows,exclusions=_predictive_surface(
        games=games,
        current_snapshots=[],
        prior_snapshots=[snap(1,2015,14,12),snap(2,2015,14,12)],
    )
    assert [r["game_id"] for r in rows]==["2"]
    assert exclusions==[{
        "game_id":"1","season":2015,"week":2,
        "reason":"CFB_SDV_2015_SUPPORT_ONLY_NO_2014_PRIOR",
    }]
    assert rows[0]["home_current_metrics"]["games_in_sample"]==0


def test_missing_week2_current_snapshot_is_explicit_exclusion():
    games=[{"game_id":3,"season":2016,"week":2,"home_id":1,"away_id":2,"neutral_site":False}]
    rows,exclusions=_predictive_surface(
        games=games,
        current_snapshots=[snap(1,2016,1,1)],
        prior_snapshots=[snap(1,2015,14,12),snap(2,2015,14,12)],
    )
    assert rows==[]
    assert exclusions[0]["game_id"]=="3"
    assert exclusions[0]["reason"]=="CFB_SDV_PREGAME_SNAPSHOT_MISSING"


def test_incomplete_advanced_join_game_is_explicitly_scoped_out():
    datasets={
        "cfb_schedules":[
            {"game_id":"1","season":"2025","week":"1"},
            {"game_id":"2","season":"2025","week":"2"},
        ],
        "espn_cfb_adv_team":[
            {"game_id":"1","season":"2025","week":"1","pos_team":"10"},
            {"game_id":"1","season":"2025","week":"1","pos_team":"20"},
            {"game_id":"2","season":"2025","week":"2","pos_team":"10"},
            {"game_id":"2","season":"2025","week":"2","pos_team":"20"},
        ],
        "espn_cfb_adv_situational":[
            {"game_id":"1","season":"2025","week":"1","pos_team":"10"},
            {"game_id":"1","season":"2025","week":"1","pos_team":"20"},
            {"game_id":"2","season":"2025","week":"2","pos_team":"10"},
        ],
        "espn_cfb_adv_drives":[
            {"game_id":"1","season":"2025","pos_team":"10"},
            {"game_id":"1","season":"2025","pos_team":"20"},
            {"game_id":"2","season":"2025","pos_team":"10"},
            {"game_id":"2","season":"2025","pos_team":"20"},
        ],
    }
    scoped,excluded=_scope_complete_advanced_join_games(datasets)
    assert excluded==[{
        "game_id":"2",
        "reason":"CFB_SDV_INCOMPLETE_OR_TEMPORALLY_INCONSISTENT_ADVANCED_JOIN",
        "row_identity_by_dataset":{
            "espn_cfb_adv_team":[[10,2025,2],[20,2025,2]],
            "espn_cfb_adv_situational":[[10,2025,2]],
            "espn_cfb_adv_drives":[[10,2025,2],[20,2025,2]],
        },
        "schedule_season_week":[2025,2],
    }]
    for dataset in ("espn_cfb_adv_team","espn_cfb_adv_situational","espn_cfb_adv_drives"):
        assert {row["game_id"] for row in scoped[dataset]}=={"1"}
    assert {row["game_id"] for row in datasets["espn_cfb_adv_team"]}=={"1","2"}


def test_temporal_disagreement_is_scoped_out_before_snapshot_filtering():
    datasets={
        "cfb_schedules":[{"game_id":"7","season":"2025","week":"4"}],
        "espn_cfb_adv_team":[
            {"game_id":"7","season":"2025","week":"4","pos_team":"10"},
            {"game_id":"7","season":"2025","week":"4","pos_team":"20"},
        ],
        "espn_cfb_adv_situational":[
            {"game_id":"7","season":"2025","week":"4","pos_team":"10"},
            {"game_id":"7","season":"2025","week":"5","pos_team":"20"},
        ],
        "espn_cfb_adv_drives":[
            {"game_id":"7","season":"2025","pos_team":"10"},
            {"game_id":"7","season":"2025","pos_team":"20"},
        ],
    }
    scoped,excluded=_scope_complete_advanced_join_games(datasets)
    assert excluded[0]["game_id"]=="7"
    assert excluded[0]["reason"]=="CFB_SDV_INCOMPLETE_OR_TEMPORALLY_INCONSISTENT_ADVANCED_JOIN"
    assert excluded[0]["schedule_season_week"]==[2025,4]
    assert excluded[0]["row_identity_by_dataset"]["espn_cfb_adv_situational"]==[
        [10,2025,4],[20,2025,5]
    ]
    for dataset in ("espn_cfb_adv_team","espn_cfb_adv_situational","espn_cfb_adv_drives"):
        assert scoped[dataset]==[]


def test_unresolved_venue_bindings_reports_all_missing_ids_in_stable_order():
    rows=[
        {"game_id":"20"},
        {"game_id":"10"},
        {"game_id":"30"},
    ]
    schedules={
        "10":{"game_id":"10","venue_id":"2031","venue":"Pitbull Stadium"},
        "20":{"game_id":"20","venue_id":"9999","venue":"Missing B"},
        "30":{"game_id":"30","venue_id":"218","venue":"FIU Stadium"},
    }
    venues={
        218:{"venue_id":218,"name":"FIU Stadium","latitude":25.75,"longitude":-80.38,"game_indoor":False},
    }
    unresolved=_unresolved_venue_bindings(
        predictive_rows=rows,
        schedule_by_game=schedules,
        venues=venues,
    )
    assert unresolved==[
        {"game_id":"10","venue_id":2031,"venue_name":"Pitbull Stadium"},
        {"game_id":"20","venue_id":9999,"venue_name":"Missing B"},
    ]
