from scripts.materialize_cfb_sportsdataverse_training import _predictive_surface, _scope_complete_advanced_join_games
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
        "cfb_schedules":[],
        "espn_cfb_adv_team":[
            {"game_id":"1","season":"2025","pos_team":"10"},
            {"game_id":"1","season":"2025","pos_team":"20"},
            {"game_id":"2","season":"2025","pos_team":"10"},
            {"game_id":"2","season":"2025","pos_team":"20"},
        ],
        "espn_cfb_adv_situational":[
            {"game_id":"1","season":"2025","pos_team":"10"},
            {"game_id":"1","season":"2025","pos_team":"20"},
            {"game_id":"2","season":"2025","pos_team":"10"},
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
        "reason":"CFB_SDV_INCOMPLETE_ADVANCED_JOIN",
        "team_ids_by_dataset":{
            "espn_cfb_adv_team":[10,20],
            "espn_cfb_adv_situational":[10],
            "espn_cfb_adv_drives":[10,20],
        },
    }]
    for dataset in ("espn_cfb_adv_team","espn_cfb_adv_situational","espn_cfb_adv_drives"):
        assert {row["game_id"] for row in scoped[dataset]}=={"1"}
    assert {row["game_id"] for row in datasets["espn_cfb_adv_team"]}=={"1","2"}
