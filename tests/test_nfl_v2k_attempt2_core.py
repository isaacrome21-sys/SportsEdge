from sportsedge.sports.nfl.v2k_drive_core import DriveRow
from sportsedge.sports.nfl.v2k_drive_core_v2 import fit_attempt2, simulate_joint_game_v2

def row(g,i,off,defn,ob,db,oa,da,out="PUNT_OTHER"):
    return DriveRow(g,2020,1,"2020-01-01",i,off,defn,75.0,out,ob,db,oa,da,4,60,source_manifest_sha256="x",source_code_sha="y")

def test_attempt2_home_identity_is_schedule_bound():
    rows=(row("g",0,"A","B",0,0,7,0,"TD"),row("g",1,"B","A",0,7,3,7,"FG"))
    fit=fit_attempt2(rows,{"g":{"home_team":"A","away_team":"B"}})
    assert fit.home_field.league_points==4.0
    assert fit.margin_clustering.signed_key_mass[3]==0.0

def test_attempt2_refuses_missing_home_identity():
    rows=(row("g",0,"A","B",0,0,0,0),)
    try: fit_attempt2(rows,{})
    except ValueError as e: assert str(e)=="V2K_ATTEMPT2_HOME_IDENTITY_MISSING"
    else: raise AssertionError("missing schedule identity accepted")

def test_key_structure_uses_training_scoring_mix():
    rows=(row("g",0,"A","B",0,0,3,0,"FG"),row("g",1,"B","A",0,3,7,3,"TD"))
    fit=fit_attempt2(rows,{"g":{"home_team":"A","away_team":"B"}})
    assert fit.margin_clustering.fg_rate==0.5
    assert fit.margin_clustering.td_rate==0.5


def test_scoring_calibration_is_not_algebraic_identity():
    # Context effects can overstate scoring even when the league baseline is
    # fitted on these same rows. Attempt 2 must be able to move scoring mass.
    rows=(
        row("g1",0,"A","B",0,0,7,0,"TD"),
        row("g1",1,"B","A",0,7,0,7,"PUNT_OTHER"),
        row("g2",0,"A","B",0,0,0,0,"PUNT_OTHER"),
        row("g2",1,"B","A",0,0,0,0,"PUNT_OTHER"),
    )
    fit=fit_attempt2(rows,{
        "g1":{"home_team":"A","away_team":"B"},
        "g2":{"home_team":"A","away_team":"B"},
    })
    scoring={fit.scoring.outcome_factor[k] for k in ("TD","FG","SAFETY","DEF_ST_SCORE")}
    assert len(scoring)==1
    assert next(iter(scoring)) != 1.0


def test_attempt2_simulation_replay_is_deterministic():
    rows=(
        row("g1",0,"A","B",0,0,7,0,"TD"),
        row("g1",1,"B","A",0,7,3,7,"FG"),
        row("g2",0,"A","B",0,0,0,0,"PUNT_OTHER"),
        row("g2",1,"B","A",0,0,0,0,"PUNT_OTHER"),
    )
    fit=fit_attempt2(rows,{
        "g1":{"home_team":"A","away_team":"B"},
        "g2":{"home_team":"A","away_team":"B"},
    })
    a=simulate_joint_game_v2(fit,"A","B",season=2025,seed=12345,regulation_drives=4)
    b=simulate_joint_game_v2(fit,"A","B",season=2025,seed=12345,regulation_drives=4)
    assert a==b
    assert a.margin==a.home_score-a.away_score
    assert a.total==a.home_score+a.away_score
    assert a.team_totals=={"A":a.home_score,"B":a.away_score}


def test_attempt2_simulation_rejects_invalid_identity_and_drive_count():
    rows=(row("g",0,"A","B",0,0,0,0),)
    fit=fit_attempt2(rows,{"g":{"home_team":"A","away_team":"B"}})
    for kwargs,message in (
        ({"home_team":"A","away_team":"A"},"V2K_TEAMS_MUST_DIFFER"),
        ({"home_team":"A","away_team":"B","regulation_drives":0},"V2K_REGULATION_DRIVES_INVALID"),
        ({"home_team":"A","away_team":"B","opening_possession":"C"},"V2K_OPENING_POSSESSION_INVALID"),
    ):
        try:
            simulate_joint_game_v2(fit,season=2025,seed=1,**kwargs)
        except ValueError as e:
            assert str(e)==message
        else:
            raise AssertionError(message+" accepted")


def test_attempt2_home_field_moves_home_scoring_probability_up():
    rows=(
        row("g1",0,"A","B",0,0,7,0,"TD"),
        row("g1",1,"B","A",0,7,0,7,"PUNT_OTHER"),
        row("g2",0,"A","B",0,0,3,0,"FG"),
        row("g2",1,"B","A",0,3,0,3,"PUNT_OTHER"),
    )
    fit=fit_attempt2(rows,{
        "g1":{"home_team":"A","away_team":"B"},
        "g2":{"home_team":"A","away_team":"B"},
    })
    from sportsedge.sports.nfl.v2k_drive_core_v2 import _corrected_probs
    home=_corrected_probs(fit,"A","B",home_team="A",start_field=75.0,bucket="NORMAL")
    away=_corrected_probs(fit,"B","A",home_team="A",start_field=75.0,bucket="NORMAL")
    assert home["TD"]+home["FG"] > away["TD"]+away["FG"]


def test_attempt2_key_mix_changes_fg_td_balance_without_margin_forcing():
    rows=(
        row("g1",0,"A","B",0,0,3,0,"FG"),
        row("g1",1,"B","A",0,3,7,3,"TD"),
        row("g2",0,"A","B",0,0,3,0,"FG"),
        row("g2",1,"B","A",0,3,0,3,"PUNT_OTHER"),
        row("g3",0,"A","B",0,0,7,0,"TD"),
        row("g3",1,"B","A",0,7,3,7,"FG"),
    )
    fit=fit_attempt2(rows,{
        "g1":{"home_team":"A","away_team":"B"},
        "g2":{"home_team":"A","away_team":"B"},
        "g3":{"home_team":"A","away_team":"B"},
    })
    from sportsedge.sports.nfl.v2k_drive_core_v2 import _corrected_probs
    raw=fit.baseline.probabilities("A","B",start_yardline_100=75.0,state_bucket="NORMAL")
    corrected=_corrected_probs(fit,"A","B",home_team="A",start_field=75.0,bucket="NORMAL")
    observed=fit.margin_clustering.fg_rate/fit.margin_clustering.td_rate
    raw_ratio=raw["FG"]/max(raw["TD"],1e-12)
    corrected_ratio=corrected["FG"]/max(corrected["TD"],1e-12)
    # Correction should move the contextual ratio toward the training scoring mix.
    assert abs(corrected_ratio-observed) <= abs(raw_ratio-observed)+1e-12
    assert set(corrected)==set(raw)
    assert abs(sum(corrected.values())-1.0)<1e-12


def test_attempt2_simulation_rejects_invalid_overtime_limit():
    rows=(
        row("g1",0,"A","B",0,0,7,0,"TD"),
        row("g1",1,"B","A",0,7,0,7,"PUNT_OTHER"),
    )
    fit=fit_attempt2(rows,{"g1":{"home_team":"A","away_team":"B"}})
    import pytest
    with pytest.raises(ValueError,match="V2K_MAX_OVERTIME_DRIVES_INVALID"):
        simulate_joint_game_v2(fit,"A","B",season=2025,seed=1,max_overtime_drives=1)


def test_attempt2_preflight_accepts_exact_frozen_identity():
    from sportsedge.sports.nfl import v2k_attempt2_validation as v
    result=v.preflight(paths=1,smoke=True)
    assert result["root_seed"]==13631901020752177054
    assert result["contract"]["status"]=="FROZEN_ATTEMPT2_READY_FOR_DEVELOPMENT_VALIDATION"
    assert result["smoke"] is True


def test_attempt2_preflight_rejects_non_smoke_below_floor():
    import pytest
    from sportsedge.sports.nfl import v2k_attempt2_validation as v
    with pytest.raises(SystemExit,match="V2K_ATTEMPT2_PATH_COUNT_INVALID"):
        v.preflight(paths=9999,smoke=False)


def test_attempt2_parallel_fold_matches_serial():
    from sportsedge.sports.nfl.v2k_attempt2_validation import run_fold_shard
    rows=(
        row("g1",0,"A","B",0,0,7,0,"TD"),
        row("g1",1,"B","A",0,7,3,7,"FG"),
        row("g2",0,"C","D",0,0,3,0,"FG"),
        row("g2",1,"D","C",0,3,0,3,"PUNT_OTHER"),
        row("g3",0,"A","B",0,0,7,0,"TD"),
        row("g3",1,"B","A",0,7,0,7,"PUNT_OTHER"),
        row("g4",0,"C","D",0,0,3,0,"FG"),
        row("g4",1,"D","C",0,3,0,3,"PUNT_OTHER"),
    )
    identity={
        "g1":{"game_id":"g1","season":2020,"week":1,"home_team":"A","away_team":"B"},
        "g2":{"game_id":"g2","season":2020,"week":1,"home_team":"C","away_team":"D"},
        "g3":{"game_id":"g3","season":2021,"week":1,"home_team":"A","away_team":"B"},
        "g4":{"game_id":"g4","season":2021,"week":1,"home_team":"C","away_team":"D"},
    }
    fold={"fold_id":"FX","train_seasons":[2020],"test_season":2021}
    drives={2020:[r for r in rows if r.season==2020],2021:[r for r in rows if r.season==2021]}
    serial=run_fold_shard(fold=fold,drives_by_season=drives,identity=identity,root_seed=99,paths=8,shard_index=0,shard_count=1,workers=1)
    parallel=run_fold_shard(fold=fold,drives_by_season=drives,identity=identity,root_seed=99,paths=8,shard_index=0,shard_count=1,workers=2)
    assert serial==parallel
