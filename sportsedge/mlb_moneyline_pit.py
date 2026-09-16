"""Strict point-in-time contract for the MLB MONEYLINE Model_P lane.

This module is deliberately market-blind. It accepts only baseball observations
whose availability timestamp is known and strictly precedes the target game's
scheduled start. Sportsbook prices, implied probabilities, consensus and public
betting data are not valid inputs.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json
from math import isfinite
from statistics import fmean
from typing import Any, Iterable, Mapping
PIT_VERSION = "mlb_moneyline_pit_v1"
class MLBMoneylinePITError(ValueError): pass
def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime): out=value
    else:
        try: out=datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
        except ValueError as exc: raise MLBMoneylinePITError(f"{field}: invalid timestamp") from exc
    if out.tzinfo is None: raise MLBMoneylinePITError(f"{field}: timezone required")
    return out.astimezone(timezone.utc)
def _number(value: Any, field: str) -> float:
    if isinstance(value,bool): raise MLBMoneylinePITError(f"{field}: boolean invalid")
    try: out=float(value)
    except (TypeError,ValueError) as exc: raise MLBMoneylinePITError(f"{field}: nonnumeric") from exc
    if not isfinite(out): raise MLBMoneylinePITError(f"{field}: nonfinite")
    return out
def _sha(value: Any)->str: return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()
def build_moneyline_feature(*,game_pk:int,away_team_id:int,home_team_id:int,event_start_ts:Any,observations:Iterable[Mapping[str,Any]],window:int=30,minimum:int=10)->dict[str,Any]:
    start=_utc(event_start_ts,"event_start_ts")
    if window<minimum or minimum<1: raise MLBMoneylinePITError("invalid window/minimum")
    by_team={int(away_team_id):[],int(home_team_id):[]}
    for raw in observations:
        try: team_id=int(raw.get("team_id"))
        except (TypeError,ValueError) as exc: raise MLBMoneylinePITError("team_id: invalid") from exc
        if team_id not in by_team: continue
        asof=_utc(raw.get("feature_asof_ts"),"feature_asof_ts")
        if asof>=start: raise MLBMoneylinePITError(f"PIT_LEAKAGE: team_id={team_id} feature_asof_ts={asof.isoformat()} event_start_ts={start.isoformat()}")
        by_team[team_id].append((asof,_number(raw.get("runs"),"runs"),raw))
    selected={}
    for team_id,rows in by_team.items():
        rows.sort(key=lambda r:r[0]); use=rows[-window:]
        if len(use)<minimum: raise MLBMoneylinePITError(f"PIT_INSUFFICIENT_HISTORY: team_id={team_id} n={len(use)} minimum={minimum}")
        selected[team_id]=use
    away=selected[int(away_team_id)]; home=selected[int(home_team_id)]; feature_asof=max(r[0] for r in away+home)
    if feature_asof>=start: raise MLBMoneylinePITError("PIT_LEAKAGE_AFTER_SELECTION")
    lineage=[{"team_id":int(r[2]["team_id"]),"runs":r[1],"feature_asof_ts":r[0].isoformat(),"source_game_pk":r[2].get("source_game_pk")} for r in away+home]
    lineage.sort(key=lambda r:(r["feature_asof_ts"],r["team_id"],str(r["source_game_pk"])))
    source_hash=_sha(lineage)
    return {"generic_feature_version":PIT_VERSION,"game_pk":int(game_pk),"market":"MONEYLINE","entity_id":str(game_pk),"away_mean_runs":float(fmean(r[1] for r in away)),"home_mean_runs":float(fmean(r[1] for r in home)),"feature_asof_ts":feature_asof.isoformat(),"event_start_ts":start.isoformat(),"pit_rule":"feature_asof_ts < event_start_ts","market_blind":True,"forbidden_market_inputs":["current_lines","odds","implied_probability","public_betting","consensus","handicapper_opinion"],"source":"TIMESTAMP_ATTESTED_BASEBALL_OBSERVATIONS","source_subset_hash":source_hash,"feature_source_hash":source_hash,"observation_count":len(lineage)}
