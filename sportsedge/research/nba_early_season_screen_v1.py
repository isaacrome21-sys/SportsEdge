"""PIT walk-forward MAE diagnostic for distinct NBA early-season V2.

Only measures projected per-player per-game realized means versus the
unadjusted previous-season player mean; NO sportsbook line, price, EV,
market admission, V1 forward-row creation or promotion.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from statistics import mean
from math import isfinite

from .nba_early_season_prop_v2 import project_early_prop, STATS

SCREEN="NBA_EARLY_SEASON_V2_HISTORICAL_MAE_SCREEN_V1"


def _clock(v, field):
    try:
        t = v if isinstance(v, datetime) else datetime.fromisoformat(
            str(v).replace("Z","+00:00"))
    except (TypeError,ValueError) as e:
        raise ValueError(field+"_INVALID") from e
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(field+"_NAIVE")
    return t.astimezone(timezone.utc)


def _stat(row, stat):
    fields=("points","rebounds","assists") if stat=="pra" else (stat,)
    vals=[]
    for f in fields:
        x=row.get(f)
        if isinstance(x,bool):
            raise ValueError("NBA_EARLY_SCREEN_STAT_INVALID")
        try: z=float(x)
        except (ValueError,TypeError) as e: raise ValueError("NBA_EARLY_SCREEN_STAT_INVALID") from e
        if not isfinite(z) or z<0:
            raise ValueError("NBA_EARLY_SCREEN_STAT_INVALID")
        vals.append(z)
    return sum(vals)


def screen_early_prop_mae(records, targets, *, stat):
    if stat not in STATS:
        raise ValueError("NBA_EARLY_SCREEN_STAT_UNSUPPORTED")
    history=list(records)
    ids=set()
    entries=[]
    blocked={}
    for tgt in sorted(targets,key=lambda t:str(t.get("game_date"))):
        gid=str(tgt.get("game_id") or "").strip()
        player=str(tgt.get("player_id") or "").strip()
        team=str(tgt.get("team_id") or "").strip()
        if not gid or not player or not team or (gid,player) in ids:
            raise ValueError("NBA_EARLY_SCREEN_TARGET_IDENTITY_OR_DUPLICATE")
        ids.add((gid,player))
        if not str(tgt.get("source_ref") or "").strip():
            raise ValueError("NBA_EARLY_SCREEN_OUTCOME_SOURCE_REQUIRED")
        decision=_clock(tgt.get("decision_as_of"),"NBA_EARLY_SCREEN_DECISION")
        tip=_clock(tgt.get("tipoff"),"NBA_EARLY_SCREEN_TIP")
        observed=_clock(tgt.get("observed_at"),"NBA_EARLY_SCREEN_RESULT")
        if not decision<tip<observed:
            raise ValueError("NBA_EARLY_SCREEN_TEMPORAL_ORDER_INVALID")
        year=int(tgt["season"])
        target_date=str(tgt.get("game_date") or "")
        try:
            declared_date=date.fromisoformat(target_date)
        except (TypeError, ValueError) as e:
            raise ValueError("NBA_EARLY_SCREEN_TARGET_GAME_DATE_INVALID") from e
        # A caller's slate-date string must never move the target across
        # the prior-history cutoff. Midnight UTC may be previous-day Chicago.
        if tip.astimezone(ZoneInfo("America/Chicago")).date()!=declared_date:
            raise ValueError("NBA_EARLY_SCREEN_TARGET_LOCAL_DATE_MISMATCH")
        actual=_stat(tgt,stat)
        if float(tgt.get("minutes") or 0)<=0:
            blocked["TARGET_DNP"]=blocked.get("TARGET_DNP",0)+1
            continue
        out=project_early_prop(history,player_id=player,target_team_id=team,
                               target_season=year,target_date=target_date,
                               as_of=decision,stat=stat,line=0.0)
        if out["status"]!="RESEARCH_PROJECTION":
            k=out["reason"] if out["status"]=="REFUSED" else out["status"]
            blocked[k]=blocked.get(k,0)+1
            continue
        prior=[]
        for row in history:
            if str(row.get("player_id") or "")!=player:
                continue
            if int(row.get("season"))!=year-1:
                continue
            if str(row.get("game_date") or "")>=target_date:
                continue
            if _clock(row.get("observed_at"),"NBA_EARLY_SCREEN_PRIOR_RESULT")>=decision:
                continue
            if float(row.get("minutes") or 0)<=0:
                continue
            prior.append(_stat(row,stat))
        if not prior:
            raise ValueError("NBA_EARLY_SCREEN_PRIOR_BASELINE_MISSING")
        baseline=mean(prior)
        entries.append({"player_id":player,"event_id":gid,"game_date":target_date,
                        "stat":stat,"actual":actual,"model_mean":out["model_mean"],
                        "baseline_mean":baseline,
                        "model_error":out["model_mean"]-actual,
                        "baseline_error":baseline-actual})
    return {"screen_id":SCREEN,"status":"HISTORICAL_SCREEN_ONLY",
            "model":"NBA_EARLY_SEASON_PROP_EMPIRICAL_CHALLENGER_V2",
            "stat":stat,"scored":len(entries),
            "blocked":blocked,"distinct_dates":len({e["game_date"] for e in entries}),
            "model_mae":mean(abs(e["model_error"]) for e in entries) if entries else None,
            "prior_season_mae":mean(abs(e["baseline_error"]) for e in entries) if entries else None,
            "market_vintage":"NONE_NO_PROP_QUOTES",
            "validation_authority":"NONE", "research_only":True,
            "play_authority":False,"rows":entries}
