"""Research-only possession-ordered NFL challenger baseline.

Deliberately state-naive: alternating possessions, deterministic rule identity,
clock consumption, and halftime possession flip. No score/time-dependent coaching
behavior is allowed in this baseline. It has zero production/promotion authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np

Outcome=Literal["TD","FG","PUNT","TURNOVER","DOWNS"]

@dataclass(frozen=True)
class Possession:
    index:int; half:int; offense:str; defense:str
    start_seconds:int; end_seconds:int; outcome:Outcome; points:int

@dataclass(frozen=True)
class PossessionPath:
    game_id:str; simulation_id:int; home_team:str; away_team:str
    opening_receiver:str; second_half_receiver:str
    possessions:tuple[Possession,...]
    @property
    def home_score(self): return sum(p.points for p in self.possessions if p.offense==self.home_team)
    @property
    def away_score(self): return sum(p.points for p in self.possessions if p.offense==self.away_team)
    @property
    def margin(self): return self.home_score-self.away_score
    @property
    def total(self): return self.home_score+self.away_score

class PossessionChallengerBaseline:
    """Development baseline; parameters must be fit/frozen outside holdout."""
    def __init__(self,*,game_id,home_team,away_team,seed,
                 td_rate=.22,fg_rate=.16,turnover_rate=.11,downs_rate=.04,
                 mean_drive_seconds=155.0,opening_receiver_home_prob=.5):
        if seed is None: raise ValueError("EXPLICIT_SEED_REQUIRED")
        if home_team==away_team: raise ValueError("HOME_AWAY_TEAM_COLLISION")
        rates=[td_rate,fg_rate,turnover_rate,downs_rate]
        if any(x<0 for x in rates) or sum(rates)>1: raise ValueError("INVALID_DRIVE_RATES")
        if mean_drive_seconds<=0: raise ValueError("INVALID_DRIVE_DURATION")
        self.game_id=game_id; self.home_team=home_team; self.away_team=away_team
        self.seed=int(seed); self.rng=np.random.default_rng(self.seed)
        self.rates=np.array([td_rate,fg_rate,1-sum(rates),turnover_rate,downs_rate],float)
        self.mean_drive_seconds=float(mean_drive_seconds)
        self.opening_receiver_home_prob=float(opening_receiver_home_prob)

    def _other(self,t): return self.away_team if t==self.home_team else self.home_team
    def _outcome(self):
        o=str(self.rng.choice(np.array(["TD","FG","PUNT","TURNOVER","DOWNS"]),p=self.rates))
        return o, 7 if o=="TD" else 3 if o=="FG" else 0
    def _half(self,*,simulation_id,half,receiver,start_index):
        offense=receiver; remaining=1800; out=[]; idx=start_index
        while remaining>0:
            duration=max(1,int(round(self.rng.gamma(shape=4.0,scale=self.mean_drive_seconds/4.0))))
            duration=min(duration,remaining)
            outcome,points=self._outcome()
            out.append(Possession(idx,half,offense,self._other(offense),remaining,remaining-duration,outcome,points))
            remaining-=duration; offense=self._other(offense); idx+=1
        return out,idx

    def simulate_one(self,simulation_id):
        opening=self.home_team if self.rng.random()<self.opening_receiver_home_prob else self.away_team
        second=self._other(opening)
        h1,idx=self._half(simulation_id=simulation_id,half=1,receiver=opening,start_index=0)
        h2,_=self._half(simulation_id=simulation_id,half=2,receiver=second,start_index=idx)
        return PossessionPath(self.game_id,simulation_id,self.home_team,self.away_team,opening,second,tuple(h1+h2))

    def simulate(self,n):
        return [self.simulate_one(i) for i in range(max(0,int(n)))]


@dataclass(frozen=True)
class VectorizedSummary:
    margins: np.ndarray
    totals: np.ndarray
    home_possessions: np.ndarray
    away_possessions: np.ndarray
    outcome_counts: np.ndarray

    def structural_metrics(self):
        n=max(1,len(self.margins))
        return {
            "mean_margin":float(np.mean(self.margins)),
            "mean_total":float(np.mean(self.totals)),
            "mean_possessions_per_team":float(np.mean(self.home_possessions+self.away_possessions)/2.0),
            "margin_mass_3":float(np.mean(np.abs(self.margins)==3)),
            "margin_mass_7":float(np.mean(np.abs(self.margins)==7)),
            "margin_mass_10":float(np.mean(np.abs(self.margins)==10)),
            "paths":int(n),
        }

class VectorizedPossessionChallengerBaseline:
    """Array-state implementation of the state-naive reference baseline."""
    OUTCOMES=np.array(["TD","FG","PUNT","TURNOVER","DOWNS"])
    POINTS=np.array([7,3,0,0,0],dtype=np.int16)

    def __init__(self,*,seed,td_rate=.22,fg_rate=.16,turnover_rate=.11,
                 downs_rate=.04,mean_drive_seconds=155.0,
                 opening_receiver_home_prob=.5,home_strength=0.0,away_strength=0.0):
        if seed is None: raise ValueError("EXPLICIT_SEED_REQUIRED")
        base=np.array([td_rate,fg_rate,1-(td_rate+fg_rate+turnover_rate+downs_rate),turnover_rate,downs_rate],float)
        if np.any(base<0): raise ValueError("INVALID_DRIVE_RATES")
        self.seed=int(seed); self.rng=np.random.default_rng(self.seed); self.base=base
        self.mean_drive_seconds=float(mean_drive_seconds)
        self.opening_receiver_home_prob=float(opening_receiver_home_prob)
        self.home_strength=float(home_strength); self.away_strength=float(away_strength)

    def _rates(self,home_offense):
        # Development-only matchup dispersion. Strength shifts TD vs punt mass
        # symmetrically and is supplied PIT by the evaluator, never learned here.
        delta=np.where(home_offense,self.home_strength-self.away_strength,self.away_strength-self.home_strength)
        shift=np.clip(delta/100.0,-.08,.08)
        p=np.broadcast_to(self.base,(len(home_offense),5)).copy()
        p[:,0]+=shift; p[:,2]-=shift
        if np.any(p<0): raise ValueError("STRENGTH_SHIFT_INVALID")
        return p

    def simulate(self,n):
        n=int(n)
        if n<=0:
            z=np.zeros(0,dtype=np.int16); return VectorizedSummary(z,z,z,z,np.zeros((0,5),dtype=np.int32))
        home_score=np.zeros(n,dtype=np.int16); away_score=np.zeros(n,dtype=np.int16)
        hp=np.zeros(n,dtype=np.int16); ap=np.zeros(n,dtype=np.int16); counts=np.zeros((n,5),dtype=np.int16)
        opening_home=self.rng.random(n)<self.opening_receiver_home_prob
        for half in (1,2):
            home_offense=opening_home.copy() if half==1 else ~opening_home
            remaining=np.full(n,1800,dtype=np.int32); active=remaining>0
            while np.any(active):
                ids=np.flatnonzero(active); m=len(ids)
                dur=np.maximum(1,np.rint(self.rng.gamma(4.0,self.mean_drive_seconds/4.0,size=m)).astype(np.int32))
                dur=np.minimum(dur,remaining[ids])
                rates=self._rates(home_offense[ids])
                u=self.rng.random(m); choice=(u[:,None]>np.cumsum(rates,axis=1)).sum(axis=1)
                pts=self.POINTS[choice]
                h=home_offense[ids]
                home_score[ids]+=np.where(h,pts,0).astype(np.int16)
                away_score[ids]+=np.where(~h,pts,0).astype(np.int16)
                hp[ids]+=h.astype(np.int16); ap[ids]+=(~h).astype(np.int16)
                np.add.at(counts,(ids,choice),1)
                remaining[ids]-=dur; home_offense[ids]=~home_offense[ids]; active=remaining>0
        return VectorizedSummary(home_score-away_score,home_score+away_score,hp,ap,counts)
