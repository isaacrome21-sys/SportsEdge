"""NFL V2K Attempt-3 context-skeleton/log-ratio development core.

Market-blind implementation of the preregistered G3 architecture.  Scored use
is disabled until exact implementation identities are frozen separately.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import exp, log
from typing import Mapping, Sequence
from numpy.random import Generator, PCG64, SeedSequence
from .v2k_drive_core import (
    DriveRow, DRIVE_OUTCOMES, SimulationResult, GameState,
    normalize_drive_rows, overtime_rule_version, _state_bucket, _field_bucket,
    _draw_named, OVERTIME_RULE_2017_2024, TRUNCATION_POLICY_VERSION,
)

HALF_LIFE_SEASONS=2.0
JEFFREYS=0.5

@dataclass(frozen=True)
class SkeletonDrive:
    period:int
    clock_seconds_remaining_period:int
    start_yardline_100:float
    offense_side:str
    termination_reason:str

@dataclass(frozen=True)
class GameSkeleton:
    game_id:str
    season:int
    weight:float
    drives:tuple[SkeletonDrive,...]

@dataclass(frozen=True)
class Attempt3Fit:
    train_max_season:int
    league_probability:Mapping[str,float]
    context_probability:Mapping[tuple[str,str],Mapping[str,float]]
    offense_log_ratio:Mapping[str,Mapping[str,float]]
    defense_log_ratio:Mapping[str,Mapping[str,float]]
    home_log_effect:Mapping[str,float]
    conversion_probability:Mapping[int,float]
    skeletons:tuple[GameSkeleton,...]
    overtime_fields:tuple[tuple[float,float],...]
    fallback_fields:tuple[tuple[float,float],...]
    exceptional_points:tuple[tuple[int,float],...]

def season_weight(season:int, train_max_season:int)->float:
    if season>train_max_season:
        raise ValueError("V2K_ATTEMPT3_FUTURE_TRAINING_ROW")
    return 2.0**(-(float(train_max_season-season))/HALF_LIFE_SEASONS)

def _smooth(counts:Mapping[str,float])->dict[str,float]:
    total=sum(float(counts.get(o,0.0)) for o in DRIVE_OUTCOMES)
    den=total+JEFFREYS*len(DRIVE_OUTCOMES)
    return {o:(float(counts.get(o,0.0))+JEFFREYS)/den for o in DRIVE_OUTCOMES}

def _variance(xs:Sequence[float])->float:
    if len(xs)<2: return 0.0
    m=sum(xs)/len(xs)
    return sum((x-m)**2 for x in xs)/(len(xs)-1)

def _weighted_outcome_counts(rows:Sequence[DriveRow], max_season:int)->dict[str,float]:
    out={o:0.0 for o in DRIVE_OUTCOMES}
    for r in rows: out[r.outcome]+=season_weight(r.season,max_season)
    return out

def _weighted_choice(items, weights, rng:Generator):
    total=sum(float(w) for w in weights)
    if total<=0: raise ValueError("V2K_ATTEMPT3_WEIGHT_SUPPORT_EMPTY")
    u=float(rng.random())*total
    acc=0.0
    for item,w in zip(items,weights):
        acc+=float(w)
        if u<=acc: return item
    return items[-1]

def _build_team_log_ratios(groups, league, max_season:int)->dict[str,dict[str,float]]:
    team_rates={t:_smooth(_weighted_outcome_counts(rs,max_season)) for t,rs in groups.items()}
    eff_n={t:sum(season_weight(r.season,max_season) for r in rs) for t,rs in groups.items()}
    between={o:_variance([p[o] for p in team_rates.values()]) for o in DRIVE_OUTCOMES}
    out={}
    for team,p in team_rates.items():
        row={}
        for o in DRIVE_OUTCOMES:
            within=max(league[o]*(1.0-league[o]),1e-12)
            n=max(eff_n[team],1e-12); b=max(between[o],0.0)
            reliability=(n*b)/(n*b+within) if b>0 else 0.0
            row[o]=reliability*log(max(p[o],1e-12)/max(league[o],1e-12))
        out[team]=row
    return out

def fit_attempt3(rows:Sequence[DriveRow], schedule_identity:Mapping[str,Mapping])->Attempt3Fit:
    rows=normalize_drive_rows(rows)
    if not rows: raise ValueError("V2K_ATTEMPT3_TRAINING_ROWS_REQUIRED")
    max_season=max(r.season for r in rows)
    by_off=defaultdict(list); by_def=defaultdict(list); by_context=defaultdict(list); by_game=defaultdict(list)
    league_counts={o:0.0 for o in DRIVE_OUTCOMES}
    home_counts={o:0.0 for o in DRIVE_OUTCOMES}; away_counts={o:0.0 for o in DRIVE_OUTCOMES}
    conv=Counter(); conv_w=Counter(); overtime_fields=[]; fallback_fields=[]; exceptional=[]
    for r in rows:
        if r.game_id not in schedule_identity: raise ValueError("V2K_ATTEMPT3_SCHEDULE_IDENTITY_MISSING")
        meta=schedule_identity[r.game_id]; home=meta["home_team"]; away=meta["away_team"]
        if r.offense not in {home,away}: raise ValueError("V2K_ATTEMPT3_TEAM_IDENTITY_DRIFT")
        w=season_weight(r.season,max_season)
        league_counts[r.outcome]+=w
        (home_counts if r.offense==home else away_counts)[r.outcome]+=w
        by_off[r.offense].append(r); by_def[r.defense].append(r); by_game[r.game_id].append(r)
        bucket=_state_bucket(r.period,r.clock_seconds_remaining_period,r.offense_score_before,r.defense_score_before,overtime=r.period==5)
        by_context[(bucket,_field_bucket(r.start_yardline_100))].append(r)
        fallback_fields.append((float(r.start_yardline_100),w))
        if r.period==5: overtime_fields.append((float(r.start_yardline_100),w))
        if r.outcome=="TD": conv_w[int(r.conversion_points)]+=w
        if r.outcome=="DEF_ST_SCORE":
            pts=max(0,int(r.defense_score_after-r.defense_score_before))
            if pts>0: exceptional.append((pts,w))
    league=_smooth(league_counts)
    context={k:_smooth(_weighted_outcome_counts(v,max_season)) for k,v in by_context.items()}
    home_p=_smooth(home_counts); away_p=_smooth(away_counts)
    home_effect={o:0.5*log(max(home_p[o],1e-12)/max(away_p[o],1e-12)) for o in DRIVE_OUTCOMES}
    conv_total=sum(conv_w.values())
    conversion={p:(conv_w[p]/conv_total if conv_total else (1.0 if p==0 else 0.0)) for p in (0,1,2)}
    skeletons=[]
    for gid,grows in sorted(by_game.items()):
        meta=schedule_identity[gid]; home=meta["home_team"]; away=meta["away_team"]
        reg=[]
        for r in sorted(grows,key=lambda x:x.drive_index):
            if r.period>4: continue
            side="home" if r.offense==home else "away" if r.offense==away else None
            if side is None: raise ValueError("V2K_ATTEMPT3_SKELETON_SIDE_INVALID")
            reg.append(SkeletonDrive(r.period,r.clock_seconds_remaining_period,float(r.start_yardline_100),side,r.termination_reason))
        if reg:
            season=int(meta.get("season",grows[0].season))
            skeletons.append(GameSkeleton(gid,season,season_weight(season,max_season),tuple(reg)))
    if not skeletons: raise ValueError("V2K_ATTEMPT3_SKELETON_SUPPORT_EMPTY")
    return Attempt3Fit(max_season,league,context,
        _build_team_log_ratios(by_off,league,max_season),
        _build_team_log_ratios(by_def,league,max_season),
        home_effect,conversion,tuple(skeletons),tuple(overtime_fields),tuple(fallback_fields),tuple(exceptional))

def _probabilities(model:Attempt3Fit,offense:str,defense:str,*,home_team:str,start_field:float,bucket:str)->dict[str,float]:
    base=model.context_probability.get((bucket,_field_bucket(start_field)),model.league_probability)
    sign=1.0 if offense==home_team else -1.0
    logs={}
    for o in DRIVE_OUTCOMES:
        logs[o]=log(max(float(base[o]),1e-12))+float(model.offense_log_ratio.get(offense,{}).get(o,0.0))+float(model.defense_log_ratio.get(defense,{}).get(o,0.0))+sign*float(model.home_log_effect[o])
    mx=max(logs.values()); vals={o:exp(logs[o]-mx) for o in DRIVE_OUTCOMES}; z=sum(vals.values())
    return {o:vals[o]/z for o in DRIVE_OUTCOMES}

def _score_event(model,outcome,rng):
    conv=po=pd=0
    if outcome=="TD":
        conv=int(_draw_named(model.conversion_probability,(0,1,2),rng)); po=6+conv
    elif outcome=="FG": po=3
    elif outcome=="SAFETY": pd=2
    elif outcome=="DEF_ST_SCORE":
        if not model.exceptional_points: raise ValueError("V2K_ATTEMPT3_EXCEPTIONAL_SCORE_SUPPORT_EMPTY")
        pts=_weighted_choice([x[0] for x in model.exceptional_points],[x[1] for x in model.exceptional_points],rng); pd=int(pts)
    return conv,po,pd

def simulate_joint_game_v3(model:Attempt3Fit,home_team:str,away_team:str,*,season:int,seed:int,max_overtime_drives:int=8)->SimulationResult:
    if home_team==away_team: raise ValueError("V2K_TEAMS_MUST_DIFFER")
    if isinstance(seed,bool) or not isinstance(seed,int): raise ValueError("V2K_SEED_REQUIRED")
    if max_overtime_drives<2: raise ValueError("V2K_MAX_OVERTIME_DRIVES_INVALID")
    rng=Generator(PCG64(SeedSequence(seed)))
    sk=_weighted_choice(model.skeletons,[s.weight for s in model.skeletons],rng)
    home=away=0; path=[]
    for i,d in enumerate(sk.drives):
        offense=home_team if d.offense_side=="home" else away_team; defense=away_team if offense==home_team else home_team
        os=home if offense==home_team else away; ds=away if offense==home_team else home
        bucket=_state_bucket(d.period,d.clock_seconds_remaining_period,os,ds)
        outcome=_draw_named(_probabilities(model,offense,defense,home_team=home_team,start_field=d.start_yardline_100,bucket=bucket),DRIVE_OUTCOMES,rng)
        conv,po,pd=_score_event(model,outcome,rng)
        if offense==home_team: home+=po; away+=pd
        else: away+=po; home+=pd
        path.append({"drive_index":i,"period":d.period,"seconds_remaining_period":d.clock_seconds_remaining_period,"offense":offense,"defense":defense,"start_yardline_100":d.start_yardline_100,"state_bucket":bucket,"outcome":outcome,"conversion_points":conv,"home_score":home,"away_score":away,"termination_reason":d.termination_reason,"truncation_policy_version":TRUNCATION_POLICY_VERSION,"overtime":False,"skeleton_game_id":sk.game_id})
    if home!=away:
        return SimulationResult(home,away,home-away,home+away,{home_team:home,away_team:away},tuple(path))
    rule=overtime_rule_version(season); ot=0; possession=None
    fields=model.overtime_fields or model.fallback_fields
    while ot<max_overtime_drives and (ot<2 or home==away):
        ot+=1
        if ot==1: possession=home_team if int(rng.integers(2))==0 else away_team
        offense=possession; defense=away_team if offense==home_team else home_team
        os=home if offense==home_team else away; ds=away if offense==home_team else home
        field=float(_weighted_choice([x[0] for x in fields],[x[1] for x in fields],rng))
        bucket=_state_bucket(5,0,os,ds,overtime=True)
        outcome=_draw_named(_probabilities(model,offense,defense,home_team=home_team,start_field=field,bucket=bucket),DRIVE_OUTCOMES,rng)
        conv,po,pd=_score_event(model,outcome,rng)
        first_def=pd>0 and ot==1
        if offense==home_team: home+=po; away+=pd
        else: away+=po; home+=pd
        path.append({"drive_index":len(path),"period":5,"seconds_remaining_period":0,"offense":offense,"defense":defense,"start_yardline_100":field,"state_bucket":bucket,"outcome":outcome,"conversion_points":conv,"home_score":home,"away_score":away,"termination_reason":"NORMAL","truncation_policy_version":TRUNCATION_POLICY_VERSION,"overtime":True,"overtime_rule_version":rule})
        possession=offense if outcome=="DEF_ST_SCORE" else defense
        if first_def or (ot==1 and rule==OVERTIME_RULE_2017_2024 and po>=6) or (home!=away and ot>=2): break
    return SimulationResult(home,away,home-away,home+away,{home_team:home,away_team:away},tuple(path))
