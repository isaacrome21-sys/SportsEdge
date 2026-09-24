"""Research-only possession-ordered NFL challenger baseline.

State-naive by design: no score/time-dependent coaching policy. Fixed football
mechanics (half expiry, scoring composition, safety, regulation OT) are modeled
with explicit regular-season OT regimes. This remains a coarse drive model;
play-level expiry, penalties, kickoffs and return scores are not modeled here.
Zero production/promotion authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
import numpy as np
from .nfl_challenger_ot_rules import regular_season_ot_rules

Outcome=Literal["TD","FG","PUNT","TURNOVER","DOWNS","SAFETY","END_HALF"]

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
    def home_score(self):
        score=0
        for p in self.possessions:
            if p.points>=0 and p.offense==self.home_team: score+=p.points
            elif p.points<0 and p.offense==self.away_team: score+=-p.points
        return score
    @property
    def away_score(self):
        score=0
        for p in self.possessions:
            if p.points>=0 and p.offense==self.away_team: score+=p.points
            elif p.points<0 and p.offense==self.home_team: score+=-p.points
        return score
    @property
    def margin(self): return self.home_score-self.away_score
    @property
    def total(self): return self.home_score+self.away_score

class PossessionChallengerBaseline:
    """Slow reference implementation for equivalence tests."""
    def __init__(self,*,game_id,home_team,away_team,seed,td_rate=.22,fg_rate=.16,
                 turnover_rate=.11,downs_rate=.04,safety_rate=.003,
                 mean_drive_seconds=155.0,opening_receiver_home_prob=.5,
                 home_strength=0.0,away_strength=0.0,strength_scale=100.0,
                 strength_clip=.08,xp_make_rate=.94,two_point_try_rate=.06,
                 two_point_make_rate=.48,season=2026):
        self.ot_rules=regular_season_ot_rules(season)
        if seed is None: raise ValueError("EXPLICIT_SEED_REQUIRED")
        if home_team==away_team: raise ValueError("HOME_AWAY_TEAM_COLLISION")
        self.game_id=game_id; self.home_team=home_team; self.away_team=away_team
        self.seed=int(seed); self.rng=np.random.default_rng(self.seed)
        punt=1-(td_rate+fg_rate+turnover_rate+downs_rate+safety_rate)
        self.base=np.array([td_rate,fg_rate,punt,turnover_rate,downs_rate,safety_rate],float)
        if np.any(self.base<0): raise ValueError("INVALID_DRIVE_RATES")
        self.mean_drive_seconds=float(mean_drive_seconds)
        self.opening_receiver_home_prob=float(opening_receiver_home_prob)
        self.home_strength=float(home_strength); self.away_strength=float(away_strength)
        self.strength_scale=float(strength_scale); self.strength_clip=float(strength_clip)
        self.xp_make_rate=float(xp_make_rate); self.two_point_try_rate=float(two_point_try_rate)
        self.two_point_make_rate=float(two_point_make_rate)

    def _other(self,t): return self.away_team if t==self.home_team else self.home_team
    def _rates(self,offense):
        delta=(self.home_strength-self.away_strength) if offense==self.home_team else (self.away_strength-self.home_strength)
        shift=float(np.clip(delta/self.strength_scale,-self.strength_clip,self.strength_clip))
        p=self.base.copy(); p[0]+=shift; p[2]-=shift; p=np.clip(p,0,None); return p/p.sum()
    def _td_points(self):
        if self.rng.random()<self.two_point_try_rate:
            return 8 if self.rng.random()<self.two_point_make_rate else 6
        return 7 if self.rng.random()<self.xp_make_rate else 6
    def _outcome(self,offense):
        i=int(self.rng.choice(6,p=self._rates(offense)))
        o=("TD","FG","PUNT","TURNOVER","DOWNS","SAFETY")[i]
        return o, self._td_points() if o=="TD" else 3 if o=="FG" else -2 if o=="SAFETY" else 0
    def _half(self,half,receiver,start_index):
        offense=receiver; remaining=1800; out=[]; idx=start_index
        while remaining>0:
            raw=max(1,int(round(self.rng.gamma(4.0,self.mean_drive_seconds/4.0))))
            # A drive that consumes exactly the remaining clock is allowed to
            # finish at 0:00. Only a drive extending beyond the half is censored.
            truncated=raw>remaining; duration=min(raw,remaining)
            outcome,points=("END_HALF",0) if truncated else self._outcome(offense)
            # SAFETY points belong to the defense; encode as negative offense points.
            out.append(Possession(idx,half,offense,self._other(offense),remaining,remaining-duration,outcome,points))
            remaining-=duration; offense=self._other(offense); idx+=1
        return out,idx
    def _scores(self,ps):
        h=a=0
        for p in ps:
            if p.points>=0:
                if p.offense==self.home_team: h+=p.points
                else: a+=p.points
            else:
                if p.offense==self.home_team: a+=-p.points
                else: h+=-p.points
        return h,a
    def _overtime(self,receiver,start_index):
        """Resolve a tied game's OT with a real clock, from zero OT scores."""
        offense=receiver; remaining=self.ot_rules.period_seconds; out=[]
        h=a=0
        while remaining>0:
            raw=max(1,int(round(self.rng.gamma(4.0,self.mean_drive_seconds/4.0))))
            duration=min(raw,remaining)
            outcome,points=("END_HALF",0) if raw>remaining else self._outcome(offense)
            # A winning TD needs no try. Opening TDs before 2025 win outright;
            # later TDs omit the try only if six points already establish a lead.
            own,other=(h,a) if offense==self.home_team else (a,h)
            if outcome=="TD" and (
                (not out and self.ot_rules.opening_td_ends_game)
                or (out and own+6>other)
            ):
                points=6
            out.append(Possession(start_index+len(out),3,offense,self._other(offense),
                                  remaining,remaining-duration,outcome,points))
            remaining-=duration
            h,a=self._scores(out)
            first=len(out)==1
            if remaining==0 or outcome=="SAFETY": break
            if first and outcome=="TD" and self.ot_rules.opening_td_ends_game: break
            if not first and h!=a: break
            offense=self._other(offense)
        return out

    def simulate_one(self,simulation_id):
        opening=self.home_team if self.rng.random()<self.opening_receiver_home_prob else self.away_team
        second=self._other(opening); h1,idx=self._half(1,opening,0); h2,idx=self._half(2,second,idx)
        ps=h1+h2; h,a=self._scores(ps)
        if h==a:
            receiver=self.home_team if self.rng.random()<.5 else self.away_team
            ps.extend(self._overtime(receiver,idx))
        return PossessionPath(self.game_id,simulation_id,self.home_team,self.away_team,opening,second,tuple(ps))
    def simulate(self,n): return [self.simulate_one(i) for i in range(max(0,int(n)))]

@dataclass(frozen=True)
class VectorizedSummary:
    margins:np.ndarray; totals:np.ndarray; home_possessions:np.ndarray
    away_possessions:np.ndarray; outcome_counts:np.ndarray; overtime_possessions:np.ndarray
    def structural_metrics(self):
        n=max(1,len(self.margins))
        return {"mean_margin":float(np.mean(self.margins)),"mean_total":float(np.mean(self.totals)),
          "mean_possessions_per_team":float(np.mean(self.home_possessions+self.away_possessions)/2),
          "margin_mass_3":float(np.mean(np.abs(self.margins)==3)),
          "margin_mass_7":float(np.mean(np.abs(self.margins)==7)),
          "margin_mass_10":float(np.mean(np.abs(self.margins)==10)),
          "overtime_path_rate":float(np.mean(self.overtime_possessions>0)) if len(self.overtime_possessions) else 0.0,
          "paths":int(n)}

class VectorizedPossessionChallengerBaseline:
    OUTCOMES=np.array(["TD","FG","PUNT","TURNOVER","DOWNS","SAFETY","END_HALF"])
    POINTS=np.array([6,3,0,0,0,-2],dtype=np.int16)
    def __init__(self,*,seed,td_rate=.22,fg_rate=.16,turnover_rate=.11,downs_rate=.04,
                 safety_rate=.003,mean_drive_seconds=155.0,opening_receiver_home_prob=.5,
                 home_strength=0.0,away_strength=0.0,strength_scale=100.0,strength_clip=.08,
                 xp_make_rate=.94,two_point_try_rate=.06,two_point_make_rate=.48,season=2026):
        self.ot_rules=regular_season_ot_rules(season)
        if seed is None: raise ValueError("EXPLICIT_SEED_REQUIRED")
        punt=1-(td_rate+fg_rate+turnover_rate+downs_rate+safety_rate)
        self.base=np.array([td_rate,fg_rate,punt,turnover_rate,downs_rate,safety_rate],float)
        if np.any(self.base<0): raise ValueError("INVALID_DRIVE_RATES")
        self.rng=np.random.default_rng(int(seed)); self.mean_drive_seconds=float(mean_drive_seconds)
        self.opening_receiver_home_prob=float(opening_receiver_home_prob)
        self.home_strength=float(home_strength); self.away_strength=float(away_strength)
        self.strength_scale=float(strength_scale); self.strength_clip=float(strength_clip)
        self.xp_make_rate=float(xp_make_rate); self.two_point_try_rate=float(two_point_try_rate)
        self.two_point_make_rate=float(two_point_make_rate)
    def _rates(self,home_offense):
        d=np.where(home_offense,self.home_strength-self.away_strength,self.away_strength-self.home_strength)
        shift=np.clip(d/self.strength_scale,-self.strength_clip,self.strength_clip)
        p=np.broadcast_to(self.base,(len(home_offense),6)).copy(); p[:,0]+=shift; p[:,2]-=shift
        p=np.clip(p,0,None); return p/p.sum(axis=1,keepdims=True)
    def _td_points(self,m):
        two=self.rng.random(m)<self.two_point_try_rate
        made2=self.rng.random(m)<self.two_point_make_rate; xp=self.rng.random(m)<self.xp_make_rate
        return np.where(two,np.where(made2,8,6),np.where(xp,7,6)).astype(np.int16)
    def _drive(self,home_offense):
        rates=self._rates(home_offense); u=self.rng.random(len(home_offense))
        ch=np.minimum((u[:,None]>np.cumsum(rates,axis=1)).sum(axis=1),5)
        pts=self.POINTS[ch].copy(); td=ch==0
        if np.any(td): pts[td]=self._td_points(int(td.sum()))
        return ch,pts
    def _overtime(self,hs,aw,hp,ap,counts,ot):
        n=len(hs)
        active=hs==aw
        home=np.zeros(n,dtype=bool); home[active]=self.rng.random(int(active.sum()))<.5
        rem=np.full(n,self.ot_rules.period_seconds,dtype=np.int32)
        while np.any(active):
            ids=np.flatnonzero(active); h=home[ids]
            raw=np.maximum(1,np.rint(self.rng.gamma(4,self.mean_drive_seconds/4,size=len(ids))).astype(np.int32))
            trunc=raw>rem[ids]; dur=np.minimum(raw,rem[ids])
            ch,pts=self._drive(h); pts=np.where(trunc,0,pts)
            first=ot[ids]==0
            own=np.where(h,hs[ids],aw[ids]); other=np.where(h,aw[ids],hs[ids])
            winning_td=(ch==0) & ~trunc & (
                (first & self.ot_rules.opening_td_ends_game) | (~first & (own+6>other))
            )
            pts=np.where(winning_td,6,pts)
            normal=pts>=0; safety=pts<0
            hs[ids]+=np.where(normal & h,pts,0)+np.where(safety & ~h,-pts,0)
            aw[ids]+=np.where(normal & ~h,pts,0)+np.where(safety & h,-pts,0)
            hp[ids]+=h; ap[ids]+=~h; ot[ids]+=1
            np.add.at(counts,(ids,np.where(trunc,6,ch)),1)
            rem[ids]-=dur
            terminal=(rem[ids]==0) | safety | winning_td | (~first & (hs[ids]!=aw[ids]))
            active[ids]=~terminal
            home[ids]=~home[ids]

    def simulate(self,n):
        n=int(n)
        if n<=0:
            z=np.zeros(0,dtype=np.int16); return VectorizedSummary(z,z,z,z,np.zeros((0,7),dtype=np.int32),z)
        hs=np.zeros(n,dtype=np.int16); aw=np.zeros(n,dtype=np.int16); hp=np.zeros(n,dtype=np.int16); ap=np.zeros(n,dtype=np.int16)
        counts=np.zeros((n,7),dtype=np.int16); ot=np.zeros(n,dtype=np.int16)
        opening=self.rng.random(n)<self.opening_receiver_home_prob
        for half in (1,2):
            home=opening.copy() if half==1 else ~opening; rem=np.full(n,1800,dtype=np.int32)
            while np.any(rem>0):
                ids=np.flatnonzero(rem>0); raw=np.maximum(1,np.rint(self.rng.gamma(4,self.mean_drive_seconds/4,size=len(ids))).astype(np.int32))
                # Match the reference semantics: a drive ending exactly at 0:00
                # may score; only an overrun is converted to END_HALF.
                trunc=raw>rem[ids]; dur=np.minimum(raw,rem[ids]); ch,pts=self._drive(home[ids]); pts=np.where(trunc,0,pts)
                h=home[ids]; normal=pts>=0; safety=pts<0
                hs[ids]+=np.where(normal & h,pts,0)+np.where(safety & ~h,-pts,0)
                aw[ids]+=np.where(normal & ~h,pts,0)+np.where(safety & h,-pts,0)
                hp[ids]+=h; ap[ids]+=~h
                valid=~trunc
                np.add.at(counts,(ids[valid],ch[valid]),1)
                np.add.at(counts,(ids[trunc],np.full(int(trunc.sum()),6,dtype=np.int16)),1)
                rem[ids]-=dur; home[ids]=~home[ids]
        self._overtime(hs,aw,hp,ap,counts,ot)
        return VectorizedSummary(hs-aw,hs+aw,hp,ap,counts,ot)
