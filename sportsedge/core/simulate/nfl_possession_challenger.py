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
