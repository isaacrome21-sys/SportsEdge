"""Chronological diagnostic screen for Elo NBA sides V2, never promotion.

Market references remain INDICATIVE until the quoted vintage, bookmaker
identity and archive admission are independently corroborated. Missing
prices never become a synthesized 50/50 or -110 benchmark.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import mean

from .nba_sides_elo_v2 import project_sides

SCREEN = "NBA_ELO_SIDE_CHRONOLOGICAL_SCREEN_V1"


def _clock(v, name):
    try:
        t=v if isinstance(v,datetime) else datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except (TypeError,ValueError) as exc:
        raise ValueError(name+"_INVALID") from exc
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(name+"_NAIVE")
    return t.astimezone(timezone.utc)


def _number(x, name):
    if isinstance(x,bool):
        raise ValueError(name+"_INVALID")
    try:
        v=float(x)
    except (ValueError,TypeError) as exc:
        raise ValueError(name+"_INVALID") from exc
    if not isfinite(v):
        raise ValueError(name+"_NONFINITE")
    return v


def _implied(american):
    n=_number(american,"AMERICAN_ODDS")
    if -100<n<100:
        raise ValueError("AMERICAN_ODDS_OUT_OF_RANGE")
    return 100/(n+100) if n>0 else -n/(-n+100)


def chronological_side_screen(history, *, min_team_games=5):
    data=list(history)
    ids=set()
    ordered=[]
    for row in data:
        gid=str(row.get("event_id") or "").strip()
        if not gid or gid in ids:
            raise ValueError("NBA_SIDE_SCREEN_EVENT_ID_DUPLICATE_OR_MISSING")
        ids.add(gid)
        tip=_clock(row.get("tipoff"),"SIDE_TIP")
        observed=_clock(row.get("observed_at"),"SIDE_RESULT_AVAILABLE")
        if observed<=tip:
            raise ValueError("NBA_SIDE_SCREEN_RESULT_NOT_AFTER_TIP")
        h,a=str(row.get("home") or ""),str(row.get("away") or "")
        src=str(row.get("source_ref") or "")
        if not h or not a or h==a or not src:
            raise ValueError("NBA_SIDE_SCREEN_HISTORY_IDENTITY_MISSING")
        hs,aws=row.get("home_score"),row.get("away_score")
        if any(type(z) is not int or z<0 for z in (hs,aws)):
            raise ValueError("NBA_SIDE_SCREEN_SCORES_INVALID")
        marketfields=("home_close_spread","home_ml","away_ml")
        quoted=any(row.get(k) is not None for k in marketfields)
        quote_time=None
        if quoted:
            if not str(row.get("close_source_ref") or ""):
                raise ValueError("NBA_SIDE_SCREEN_CLOSE_SOURCE_REQUIRED")
            quote_time=_clock(row.get("close_captured_at"),"SIDE_CLOSE_CAPTURE")
            if not quote_time<tip:
                raise ValueError("NBA_SIDE_SCREEN_CLOSE_NOT_PRETIP")
        spread=None
        if row.get("home_close_spread") is not None:
            spread=_number(row["home_close_spread"],"HOME_CLOSE_SPREAD")
        ml=None
        if row.get("home_ml") is not None or row.get("away_ml") is not None:
            if row.get("home_ml") is None or row.get("away_ml") is None:
                raise ValueError("NBA_SIDE_SCREEN_ML_PAIR_REQUIRED")
            ph=_implied(row["home_ml"]); pa=_implied(row["away_ml"])
            ml=ph/(ph+pa)
        ordered.append((tip,gid,observed,h,a,hs,aws,row,spread,ml))
    ordered.sort(key=lambda q:(q[0],q[1]))
    hist=[{"game_id":gid,"tipoff":tip,"observed_at":obs,
           "source_ref":row["source_ref"],"home":h,"away":a,
           "home_score":hs,"away_score":aws,
           "season":row.get("season")}
          for tip,gid,obs,h,a,hs,aws,row,spread,ml in ordered]
    outputs=[]
    refused=0
    for tip,gid,obs,h,a,hs,aws,row,spread,ml in ordered:
        out=project_sides(hist,home=h,away=a,as_of=tip,min_team_games=min_team_games)
        if out["status"]!="RESEARCH_PROJECTION":
            refused+=1
            continue
        actual_margin=hs-aws
        if actual_margin==0:
            # NBA final-score draw has no two-way moneyline resolution.
            raise ValueError("NBA_SIDE_SCREEN_REGULATION_OR_FINAL_TIE_INVALID")
        v={"event_id":gid,"game_date":tip.date().isoformat(),
           "margin_error":out["projected_home_margin"]-actual_margin,
           "candidate_brier":(out["raw_home_win_probability"]-float(hs>aws))**2,
           "market_spread_error":None,
           "indicative_market_ml_brier":None}
        if spread is not None:
            v["market_spread_error"]=-spread-actual_margin
        if ml is not None:
            v["indicative_market_ml_brier"]=(ml-float(hs>aws))**2
        outputs.append(v)
    def mean_field(k, rows):
        return mean(row[k] for row in rows) if rows else None
    spread_rows=[v for v in outputs if v["market_spread_error"] is not None]
    ml_rows=[v for v in outputs if v["indicative_market_ml_brier"] is not None]
    return {"screen_id":SCREEN,"status":"HISTORICAL_SCREEN_ONLY",
            "market_admission":"NOT_VERIFIED","validation_authority":"NONE",
            "games_seen":len(ordered),"games_scored":len(outputs),
            "games_refused":refused,
            "distinct_dates":len({v["game_date"] for v in outputs}),
            "candidate_margin_rmse":sqrt(mean_field("squared_margin_error",[
                {**v,"squared_margin_error":v["margin_error"]**2} for v in outputs])) if outputs else None,
            "indicative_market_spread_rmse":sqrt(mean_field("squared_market_error",[
                {"squared_market_error":v["market_spread_error"]**2} for v in spread_rows])) if spread_rows else None,
            "candidate_ml_brier":mean_field("candidate_brier",outputs),
            "paired_candidate_ml_brier":mean_field("candidate_brier",ml_rows),
            "indicative_market_ml_brier":mean_field("indicative_market_ml_brier",ml_rows),
            "spread_reference_games":len(spread_rows),"ml_reference_games":len(ml_rows),
            "market_claim":"NO_VERIFIED_PROVIDER_OR_PRICE_VINTAGE",
            "research_only":True,"play_authority":False}
