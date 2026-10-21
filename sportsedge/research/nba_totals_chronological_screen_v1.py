"""Read-only chronological screen for the NBA scoring-level V2 challenger.

Historical screening is never a forward entry, even if run after a game.
A quoted 'close' is accepted as an INDICATIVE reference only when its
timestamp is pre-tip and the source and market identities are explicit.
That still does NOT certify independent provider authentication/admission.
No automatic version freeze, market admission, PLAY or promotion.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import mean

from .nba_scoring_level_v2 import predict_total

SCREEN = "NBA_SCORING_LEVEL_V2_CHRONOLOGICAL_SCREEN_V1"


def _clock(value, field):
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError) as e:
        raise ValueError(field + "_TIMESTAMP_INVALID") from e
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError(field + "_TIMESTAMP_NAIVE")
    return d.astimezone(timezone.utc)


def _finite(value, field):
    if isinstance(value, bool):
        raise ValueError(field + "_INVALID")
    try:
        n = float(value)
    except (ValueError, TypeError) as e:
        raise ValueError(field + "_INVALID") from e
    if not isfinite(n):
        raise ValueError(field + "_INVALID")
    return n


def chronological_total_screen(history, *, min_games=30):
    """Walk all fixtures; calculate prediction BEFORE that fixture's tip.

    Each real historical game row needs event_id, home/away, scores,
    tipoff, observed_at and source_ref. Optional close data must carry:
    closing_total, close_captured_at, close_source_ref. The caller's
    source string alone cannot certify the close as provider-authentic.
    Multiple seasons, date clusters and source coverage are disclosed.
    """
    rows = list(history)
    seen = set()
    ordered = []
    for x in rows:
        eid = str(x.get("event_id") or "").strip()
        if not eid or eid in seen:
            raise ValueError("NBA_TOTAL_SCREEN_DUPLICATE_OR_MISSING_EVENT")
        seen.add(eid)
        h,a = str(x.get("home") or ""),str(x.get("away") or "")
        if not h or not a or h == a or not str(x.get("source_ref") or ""):
            raise ValueError("NBA_TOTAL_SCREEN_UNVERIFIED_SCORE_SOURCE")
        tip=_clock(x.get("tipoff"),"NBA_TOTAL_TIP")
        observed=_clock(x.get("observed_at"),"NBA_TOTAL_RESULT_AVAILABLE")
        if observed <= tip:
            raise ValueError("NBA_TOTAL_SCREEN_RESULT_AVAILABLE_NOT_AFTER_TIP")
        hp,ap=_finite(x.get("home_pts"),"NBA_TOTAL_HOME_SCORE"),_finite(x.get("away_pts"),"NBA_TOTAL_AWAY_SCORE")
        if hp<0 or ap<0:
            raise ValueError("NBA_TOTAL_SCREEN_SCORE_NEGATIVE")
        close=None
        if x.get("closing_total") is not None:
            if not str(x.get("close_source_ref") or ""):
                raise ValueError("NBA_TOTAL_SCREEN_CLOSE_SOURCE_REQUIRED")
            ctime=_clock(x.get("close_captured_at"),"NBA_TOTAL_CLOSE")
            if not ctime < tip:
                raise ValueError("NBA_TOTAL_SCREEN_CLOSE_NOT_PRETIP")
            close=_finite(x["closing_total"],"NBA_TOTAL_CLOSE_LINE")
            if close<=0:
                raise ValueError("NBA_TOTAL_SCREEN_CLOSE_LINE_INVALID")
        ordered.append((tip,eid,observed,h,a,hp,ap,close,x))
    ordered.sort(key=lambda x:(x[0],x[1]))
    # We never put a future outcome into a feature set. The model's
    # result-availability PIT filter makes this safe even for same-day games.
    hist=[{"game_id":e,"tipoff":tip,"observed_at":obs,
           "source_ref":x["source_ref"],"home":h,"away":a,
           "home_pts":hp,"away_pts":ap}
          for tip,e,obs,h,a,hp,ap,c,x in ordered]
    observations=[]
    counts={"total_events":len(ordered),"model_priced":0,
            "model_refused":0,"paired_with_timestamped_market_reference":0}
    for tip,eid,observed,h,a,hp,ap,close,x in ordered:
        asof=tip  # strictly pre-tip results filtered by observed_at < asof
        model=predict_total(hist,home=h,away=a,as_of=asof,min_games=min_games)
        if model["status"]!="RESEARCH_PROJECTION":
            counts["model_refused"]+=1
            continue
        actual=hp+ap
        candidate=model["predicted_total"]
        # Climato baseline uses exactly the candidate's available PIT window
        # with no outcomes from today being treated as known before reported.
        past=sorted((z for z in hist if z["observed_at"]<asof
                     and z["tipoff"]<asof),key=lambda z:(z["tipoff"],z["game_id"]))[-450:]
        baseline=mean(z["home_pts"]+z["away_pts"] for z in past)
        entry={"event_id":eid,"event_start":tip.isoformat(),"actual":actual,
               "candidate_total":candidate,"climatology_total":baseline,
               "candidate_error":candidate-actual,
               "baseline_error":baseline-actual,
               "market_close":close,
               "independent_market_admission":"NOT_VERIFIED"}
        counts["model_priced"]+=1
        if close is not None:
            counts["paired_with_timestamped_market_reference"]+=1
            entry["market_reference_error"]=close-actual
        observations.append(entry)
    def rmse(key,data):
        return sqrt(mean(r[key]**2 for r in data)) if data else None
    with_close=[r for r in observations if r["market_close"] is not None]
    dates={r["event_start"][:10] for r in observations}
    return {"screen_id":SCREEN,"status":"HISTORICAL_SCREEN_ONLY",
            "validation_authority":"NONE","market_admission":"NOT_VERIFIED",
            "counts":counts,"distinct_scored_dates":len(dates),
            "candidate_rmse":rmse("candidate_error",observations),
            "climatology_rmse":rmse("baseline_error",observations),
            "paired_candidate_rmse":rmse("candidate_error",with_close),
            "indicative_market_reference_rmse":rmse("market_reference_error",with_close),
            "paired_games":len(with_close),
            "market_claim":"NO_VERIFIED_PROVIDER_OR_PRICE_VINTAGE",
            "rows":observations,"research_only":True,"play_authority":False}
