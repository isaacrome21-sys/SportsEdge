"""NFL V2K Attempt-2 training-only correction layer.

Development code only. Home-field identity is supplied explicitly from the
official schedule; it is never inferred from DriveRow ordering.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Sequence
from .v2k_drive_core import DriveRow, HierarchicalStrength, fit_hierarchical_strength

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
    if not rows: raise ValueError("V2K_ATTEMPT2_TRAINING_ROWS_REQUIRED")
    outcomes=tuple(baseline.league_baseline)
    n=len(rows)
    empirical={o:sum(r.outcome==o for r in rows)/n for o in outcomes}
    factors={o:empirical[o]/max(float(baseline.league_baseline[o]),1e-12) for o in outcomes}
    return ScoringCalibration(factors)

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
    return MarginClustering({k:counts[k]/n for k in counts})

def fit_attempt2(rows: Sequence[DriveRow], schedule_identity: Mapping[str, Mapping]) -> Attempt2Fit:
    baseline=fit_hierarchical_strength(rows)
    return Attempt2Fit(baseline,fit_scoring(rows,baseline),fit_home_field(rows,schedule_identity),fit_margin_clustering(rows,schedule_identity))
