import json
from math import isclose
from pathlib import Path

from sportsedge.sports.nfl.v2k_drive_core import DriveRow, DRIVE_OUTCOMES
from sportsedge.sports.nfl.v2k_drive_core_v3 import (
    Attempt3Fit, GameSkeleton, SkeletonDrive,
    fit_attempt3, season_weight, simulate_joint_game_v3,
)

NFL=Path("sportsedge/sports/nfl")

def _row(game,season,index,offense,defense,outcome,*,period=1,clock=800,field=50.0,
         osb=0,dsb=0,osa=0,dsa=0,conv=0,term="NORMAL"):
    return DriveRow(
        game_id=game,season=season,week=1,kickoff_utc=f"{season}-09-01T17:00:00Z",
        drive_index=index,offense=offense,defense=defense,start_yardline_100=field,
        outcome=outcome,offense_score_before=osb,defense_score_before=dsb,
        offense_score_after=osa,defense_score_after=dsa,period=period,
        clock_seconds_remaining_period=clock,conversion_points=conv,
        termination_reason=term,source_manifest_sha256="m",source_code_sha="c",
    )

def _one_outcome_probs(name):
    return {o:(1.0 if o==name else 0.0) for o in DRIVE_OUTCOMES}

def _manual_model(outcome):
    sk=GameSkeleton(
        "skeleton",2024,1.0,
        (SkeletonDrive(4,30,50.0,"home","END_OF_GAME"),),
    )
    return Attempt3Fit(
        train_max_season=2024,
        league_probability=_one_outcome_probs(outcome),
        context_probability={("NORMAL","MID_FIELD"):_one_outcome_probs(outcome),
                             ("OVERTIME","MID_FIELD"):_one_outcome_probs(outcome)},
        offense_log_ratio={},defense_log_ratio={},
        home_log_effect={o:0.0 for o in DRIVE_OUTCOMES},
        conversion_probability={0:0.0,1:1.0,2:0.0},
        skeletons=(sk,),overtime_fields=((50.0,1.0),),fallback_fields=((50.0,1.0),),
        exceptional_points=((6,1.0),),
    )

def test_preregistered_seed_and_attempt_budget_are_fixed():
    c=json.loads((NFL/"NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V3.json").read_text())
    assert int(c["simulation"]["root_seed"])==8538327727501875778
    assert c["simulation"]["paths_per_game"]==50000
    assert c["attempt_budget"]["development_budget_units_used_before_attempt3"]==2
    assert c["attempt_budget"]["development_budget_units_remaining_before_attempt3"]==3

def test_recency_weight_exact_two_season_half_life():
    assert season_weight(2024,2024)==1.0
    assert season_weight(2022,2024)==0.5
    assert isclose(season_weight(2023,2024),2**-0.5,rel_tol=0,abs_tol=1e-15)

def test_fit_builds_weighted_full_game_skeletons_and_home_away_sides():
    rows=[
        _row("g23",2023,0,"A","B","TD",osa=7,conv=1),
        _row("g23",2023,1,"B","A","PUNT_OTHER",osb=0,dsb=7,osa=0,dsa=7,period=4,clock=0,term="END_OF_GAME"),
        _row("g24",2024,0,"C","D","FG",osa=3),
        _row("g24",2024,1,"D","C","PUNT_OTHER",osb=0,dsb=3,osa=0,dsa=3,period=4,clock=0,term="END_OF_GAME"),
    ]
    ident={
        "g23":{"game_id":"g23","season":2023,"week":1,"home_team":"A","away_team":"B","home_score":7,"away_score":0},
        "g24":{"game_id":"g24","season":2024,"week":1,"home_team":"C","away_team":"D","home_score":3,"away_score":0},
    }
    model=fit_attempt3(rows,ident)
    assert model.train_max_season==2024
    assert [s.game_id for s in model.skeletons]==["g23","g24"]
    assert isclose(model.skeletons[0].weight,2**-0.5,rel_tol=0,abs_tol=1e-15)
    assert model.skeletons[1].weight==1.0
    assert [d.offense_side for d in model.skeletons[0].drives]==["home","away"]
    assert abs(sum(model.league_probability.values())-1.0)<1e-12

def test_non_tied_regulation_game_never_enters_overtime():
    model=_manual_model("TD")
    result=simulate_joint_game_v3(model,"H","A",season=2025,seed=17,max_overtime_drives=4)
    assert result.home_score==7
    assert result.away_score==0
    assert len(result.path)==1
    assert not any(row["overtime"] for row in result.path)

def test_tied_regulation_uses_overtime_rules_without_score_rewrite():
    model=_manual_model("PUNT_OTHER")
    result=simulate_joint_game_v3(model,"H","A",season=2025,seed=17,max_overtime_drives=4)
    assert result.home_score==0 and result.away_score==0
    assert len(result.path)>1
    assert any(row["overtime"] for row in result.path)
    assert all(row["outcome"]=="PUNT_OTHER" for row in result.path)

def test_attempt3_core_has_no_sportsbook_feature_names():
    text=(NFL/"v2k_drive_core_v3.py").read_text()
    forbidden=("spread_line","total_line","home_spread_odds","away_spread_odds","over_odds","under_odds")
    assert all(token not in text for token in forbidden)
