"""NFL V2K Attempt-2 training-only correction layer.

Development code only. Home-field identity is supplied explicitly from the
official schedule; it is never inferred from DriveRow ordering.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from .v2k_drive_core import DriveRow, HierarchicalStrength, fit_hierarchical_strength, DRIVE_OUTCOMES, SimulationResult, GameState, overtime_rule_version, _state_bucket, _draw_named, _clock_state, OVERTIME_RULE_2017_2024, TRUNCATION_POLICY_VERSION
from numpy.random import Generator, PCG64, SeedSequence

@dataclass(frozen=True)
class ScoringCalibration:
    outcome_factor: Mapping[str, float]

@dataclass(frozen=True)
class HomeFieldEffect:
    league_points: float
    team_points: Mapping[str, float]

@dataclass(frozen=True)
class MarginClustering:
    signed_key_mass: Mapping[int, float]
    fg_rate: float
    td_rate: float

@dataclass(frozen=True)
class Attempt2Fit:
    baseline: HierarchicalStrength
    scoring: ScoringCalibration
    home_field: HomeFieldEffect
    margin_clustering: MarginClustering

def _games(rows: Sequence[DriveRow]) -> dict[str, list[DriveRow]]:
    out={}
    for r in rows: out.setdefault(r.game_id,[]).append(r)
    return out

def fit_scoring(rows: Sequence[DriveRow], baseline: HierarchicalStrength) -> ScoringCalibration:
    """Fit one training-only scoring-propensity scalar.

    The old implementation divided empirical league outcome rates by the
    baseline league rates fitted from the same rows, making the correction
    effectively identity.  Here the target is actual points per drive and the
    predictor is the fully contextual hierarchical probability for each
    training drive.  A single scalar is solved before renormalization and is
    applied to scoring outcomes only; no market or held-out outcome is used.
    """
    if not rows:
        raise ValueError("V2K_ATTEMPT2_TRAINING_ROWS_REQUIRED")
    conv=sum(float(k)*float(v) for k,v in baseline.conversion_probabilities.items())
    exceptional=(sum(baseline.exceptional_score_points)/len(baseline.exceptional_score_points)
                 if baseline.exceptional_score_points else 6.0)
    points={"TD":6.0+conv,"FG":3.0,"TURNOVER":0.0,"PUNT_OTHER":0.0,
            "SAFETY":2.0,"DEF_ST_SCORE":exceptional}
    actual=sum(max(0.0,float(r.offense_score_after-r.offense_score_before))+
               max(0.0,float(r.defense_score_after-r.defense_score_before))
               for r in rows)/len(rows)
    raw=[]
    for r in rows:
        bucket=_state_bucket(r.period,r.clock_seconds_remaining_period,
                             r.offense_score_before,r.defense_score_before)
        raw.append(baseline.probabilities(r.offense,r.defense,
                    start_yardline_100=r.start_yardline_100,state_bucket=bucket))
    scoring={"TD","FG","SAFETY","DEF_ST_SCORE"}
    def expected(mult: float) -> float:
        total=0.0
        for p in raw:
            z=sum(float(v)*(mult if o in scoring else 1.0) for o,v in p.items())
            total+=sum(points[o]*float(v)*(mult if o in scoring else 1.0)
                       for o,v in p.items())/z
        return total/len(raw)
    lo,hi=0.05,5.0
    if actual<=expected(lo):
        mult=lo
    elif actual>=expected(hi):
        mult=hi
    else:
        for _ in range(60):
            mid=(lo+hi)/2.0
            if expected(mid)<actual: lo=mid
            else: hi=mid
        mult=(lo+hi)/2.0
    return ScoringCalibration({o:(mult if o in scoring else 1.0)
                               for o in DRIVE_OUTCOMES})

def fit_home_field(rows: Sequence[DriveRow], schedule_identity: Mapping[str, Mapping]) -> HomeFieldEffect:
    games=_games(rows)
    missing=set(games)-set(schedule_identity)
    if missing: raise ValueError("V2K_ATTEMPT2_HOME_IDENTITY_MISSING")
    diffs=[]; by_team={}
    for gid, grows in games.items():
        meta=schedule_identity[gid]; home=meta["home_team"]; away=meta["away_team"]
        last=max(grows,key=lambda r:r.drive_index)
        # Scores in a DriveRow are possession-relative, so use the terminal
        # row's offense identity to map the terminal score back to home/away.
        if last.offense==home:
            hs,as_=last.offense_score_after,last.defense_score_after
        elif last.offense==away:
            hs,as_=last.defense_score_after,last.offense_score_after
        else: raise ValueError("V2K_ATTEMPT2_HOME_TEAM_DRIFT")
        d=float(hs-as_); diffs.append(d); by_team.setdefault(home,[]).append(d)
    league=sum(diffs)/len(diffs)
    # Conservative partial pooling; exact shrinkage is an Attempt-2 freeze item.
    team={t:(sum(v)/len(v)*len(v)+league*16.0)/(len(v)+16.0) for t,v in by_team.items()}
    return HomeFieldEffect(league,team)

def fit_margin_clustering(rows: Sequence[DriveRow], schedule_identity: Mapping[str, Mapping]) -> MarginClustering:
    games=_games(rows); counts={-7:0,-3:0,3:0,7:0}
    for gid,grows in games.items():
        if gid not in schedule_identity: raise ValueError("V2K_ATTEMPT2_MARGIN_IDENTITY_MISSING")
        meta=schedule_identity[gid]; home=meta["home_team"]; last=max(grows,key=lambda r:r.drive_index)
        if last.offense==home: margin=last.offense_score_after-last.defense_score_after
        else: margin=last.defense_score_after-last.offense_score_after
        if margin in counts: counts[margin]+=1
    n=len(games)
    outcomes=[r.outcome for r in rows]
    return MarginClustering({k:counts[k]/n for k in counts},
                            outcomes.count("FG")/max(1,len(outcomes)),
                            outcomes.count("TD")/max(1,len(outcomes)))

def fit_attempt2(rows: Sequence[DriveRow], schedule_identity: Mapping[str, Mapping]) -> Attempt2Fit:
    baseline=fit_hierarchical_strength(rows)
    return Attempt2Fit(baseline,fit_scoring(rows,baseline),fit_home_field(rows,schedule_identity),fit_margin_clustering(rows,schedule_identity))


def _corrected_probs(model: Attempt2Fit, offense: str, defense: str, *, home_team: str, start_field: float, bucket: str):
    raw=model.baseline.probabilities(offense,defense,start_yardline_100=start_field,state_bucket=bucket)
    vals={o:max(0.0,float(raw[o]))*float(model.scoring.outcome_factor[o]) for o in DRIVE_OUTCOMES}
    # Home-field enters scoring propensity, not observed test outcomes.
    h=model.home_field.team_points.get(home_team,model.home_field.league_points)
    mult=max(0.5,min(1.5,1.0+(h/100.0)*(1.0 if offense==home_team else -1.0)))
    for o in ("TD","FG"): vals[o]*=mult
    # Key-number structure must arise from football scoring events, not from
    # rewriting final margins. Training-only empirical FG/TD balance adjusts
    # the relative probability of 3- and 7-point scoring opportunities.
    if model.margin_clustering.td_rate>0 and model.margin_clustering.fg_rate>0:
        observed_ratio=model.margin_clustering.fg_rate/model.margin_clustering.td_rate
        raw_ratio=max(float(raw["FG"]),1e-12)/max(float(raw["TD"]),1e-12)
        ratio=(observed_ratio/raw_ratio)**0.5
        vals["FG"]*=ratio
        vals["TD"]/=ratio
    z=sum(vals.values())
    return {o:vals[o]/z for o in DRIVE_OUTCOMES}

def simulate_joint_game_v2(model: Attempt2Fit,home_team:str,away_team:str,*,season:int,seed:int,regulation_drives:int|None=None,max_overtime_drives:int=8,opening_possession:str|None=None)->SimulationResult:
    if isinstance(seed,bool) or not isinstance(seed,int): raise ValueError("V2K_SEED_REQUIRED")
    b=model.baseline; rng=Generator(PCG64(SeedSequence(seed)))
    if regulation_drives is None: regulation_drives=int(b.regulation_drive_counts[int(rng.integers(len(b.regulation_drive_counts)))])
    if opening_possession is None: opening_possession=home_team if int(rng.integers(2))==0 else away_team
    second=away_team if opening_possession==home_team else home_team; half=max(1,regulation_drives//2)
    state=GameState(home_team,away_team,possession=opening_possession); path=[]; ot=0; rule=overtime_rule_version(season)
    while state.drive_index<regulation_drives or (ot<max_overtime_drives and (ot<2 or state.home_score==state.away_score)):
        in_ot=state.drive_index>=regulation_drives
        if in_ot: ot+=1
        offense=(home_team if int(rng.integers(2))==0 else away_team) if in_ot and ot==1 else state.possession
        defense=away_team if offense==home_team else home_team
        os=state.home_score if offense==home_team else state.away_score; ds=state.away_score if offense==home_team else state.home_score
        field=b.start_field_positions[int(rng.integers(len(b.start_field_positions)))]; bucket=_state_bucket(state.period,state.seconds_remaining_period,os,ds,overtime=in_ot)
        outcome=_draw_named(_corrected_probs(model,offense,defense,home_team=home_team,start_field=field,bucket=bucket),DRIVE_OUTCOMES,rng)
        conv=po=pd=0
        if outcome=="TD": conv=int(_draw_named(b.conversion_probabilities,(0,1,2),rng)); po=6+conv
        elif outcome=="FG": po=3
        elif outcome=="SAFETY": pd=2
        elif outcome=="DEF_ST_SCORE": pd=int(b.exceptional_score_points[int(rng.integers(len(b.exceptional_score_points)))])
        first_def=in_ot and ot==1 and pd>0; home,away=state.home_score,state.away_score
        if offense==home_team: home+=po; away+=pd
        else: away+=po; home+=pd
        ni=state.drive_index+1; term="NORMAL" if in_ot else ("END_OF_GAME" if ni>=regulation_drives else ("END_OF_HALF" if ni==half else "NORMAL"))
        path.append({"drive_index":state.drive_index,"offense":offense,"defense":defense,"outcome":outcome,"home_score":home,"away_score":away,"overtime":in_ot})
        period,seconds=_clock_state(ni,regulation_drives)
        nxt=second if term=="END_OF_HALF" else (offense if outcome=="DEF_ST_SCORE" else defense)
        state=GameState(home_team,away_team,nxt,home,away,5 if in_ot else period,0 if in_ot else seconds,ni,in_ot)
        if first_def or (in_ot and ot==1 and rule==OVERTIME_RULE_2017_2024 and po>=6) or (in_ot and home!=away and ot>=2): break
    return SimulationResult(state.home_score,state.away_score,state.home_score-state.away_score,state.home_score+state.away_score,{home_team:state.home_score,away_team:state.away_score},tuple(path))
