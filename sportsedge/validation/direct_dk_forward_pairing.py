"""Admit exact prospective direct-DraftKings decision/close pairs, with zero betting authority."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

UTC = timezone.utc

class DirectDKPairingError(ValueError): pass

def _ts(v: Any) -> datetime:
    try: d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    except Exception as exc: raise DirectDKPairingError("DIRECT_DK_PAIR_TIMESTAMP_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None: raise DirectDKPairingError("DIRECT_DK_PAIR_TIMESTAMP_TZ_REQUIRED")
    return d.astimezone(UTC)

def _load_policy(path: Path) -> dict[str,Any]:
    p=json.loads(path.read_text())
    if p.get("schema")!="SPORTSEDGE_DIRECT_DK_FORWARD_PAIR_ADMISSION_V1": raise DirectDKPairingError("DIRECT_DK_PAIR_POLICY_INVALID")
    if any(v is not False for v in (p.get("authority") or {}).values()): raise DirectDKPairingError("DIRECT_DK_PAIR_AUTHORITY_FORBIDDEN")
    return p

def _identity(row: Mapping[str,Any]) -> tuple[str,str,str,str]:
    market=str(row.get("market") or "")
    point=row.get("point")
    if market=="h2h": threshold="NONE"
    elif not isinstance(point,(int,float)) or isinstance(point,bool): raise DirectDKPairingError("DIRECT_DK_PAIR_POINT_REQUIRED")
    else: threshold=f"{abs(float(point)):g}" if market=="spreads" else f"{float(point):g}"
    return str(row.get("provider_event_id") or ""),str(row.get("sportsbook") or ""),market,threshold

def _validate_row(row: Mapping[str,Any], policy: Mapping[str,Any]) -> None:
    req=policy["required"]
    if row.get("schema_version")!=req["source_schema"]: raise DirectDKPairingError("DIRECT_DK_PAIR_SCHEMA_INVALID")
    if row.get("provider")!=req["provider"] or row.get("sportsbook")!=req["sportsbook"]: raise DirectDKPairingError("DIRECT_DK_PAIR_SOURCE_INVALID")
    if row.get("evidence_class")!=req["source_evidence_class"]: raise DirectDKPairingError("DIRECT_DK_PAIR_SOURCE_CLASS_INVALID")
    if row.get("promotion_authority") is not False or row.get("evidence_clock_authority") is not False: raise DirectDKPairingError("DIRECT_DK_PAIR_SOURCE_AUTHORITY_INVALID")
    if row.get("historical_backfill") is not False: raise DirectDKPairingError("DIRECT_DK_PAIR_BACKFILL_FORBIDDEN")
    digest=str(row.get("raw_sha256") or "").lower()
    if len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest): raise DirectDKPairingError("DIRECT_DK_PAIR_RAW_SHA_INVALID")
    if row.get("timestamp_semantics")!="HTTP_RESPONSE_RECEIPT_UPPER_BOUND": raise DirectDKPairingError("DIRECT_DK_PAIR_TIMESTAMP_SEMANTICS_INVALID")

def pair_rows(rows: Iterable[Mapping[str,Any]], policy: Mapping[str,Any], sport: str) -> dict[str,Any]:
    sp=(policy.get("sports") or {}).get(sport)
    if not isinstance(sp,Mapping): raise DirectDKPairingError("DIRECT_DK_PAIR_SPORT_UNSUPPORTED")
    groups: dict[tuple[str,str,str,str,str], list[dict[str,Any]]] = defaultdict(list)
    for src in rows:
        row=dict(src); _validate_row(row,policy)
        if row.get("sport_key")!=sport: continue
        capture=_ts(row["captured_at"]); start=_ts(row["commence_time"])
        first=sp.get("first_admissible_game_date")
        if first and start.date()<date.fromisoformat(first): continue
        floor=sp.get("capture_not_before_utc")
        if floor and capture<_ts(floor): continue
        ident=_identity(row)
        groups[(*ident,row["captured_at"])].append(row)
    captures: dict[tuple[str,str,str,str], list[dict[str,Any]]] = defaultdict(list)
    for key,items in groups.items():
        ident=key[:4]
        if len(items)!=2 or len({str(x.get("outcome")) for x in items})!=2: continue
        if ident[2]!="h2h" and ident[2]=="totals" and len({float(x["point"]) for x in items})!=1: continue
        if ident[2]=="spreads" and len({abs(float(x["point"])) for x in items})!=1: continue
        captures[ident].append({"captured_at":_ts(items[0]["captured_at"]),"start":_ts(items[0]["commence_time"]),"rows":sorted(items,key=lambda x:str(x["outcome"]))})
    pairs=[]
    dmin,dmax=map(float,sp["decision_window_minutes"]); cmin,cmax=map(float,sp["close_window_minutes"])
    for ident,obs in captures.items():
        for d in obs:
            dlead=(d["start"]-d["captured_at"]).total_seconds()/60
            if not dmin<=dlead<=dmax: continue
            for c in obs:
                clead=(c["start"]-c["captured_at"]).total_seconds()/60
                if not (cmin<=clead<=cmax and d["captured_at"]<c["captured_at"]<c["start"]): continue
                if [x["outcome"] for x in d["rows"]]!=[x["outcome"] for x in c["rows"]]: continue
                if [x.get("point") for x in d["rows"]]!=[x.get("point") for x in c["rows"]]: continue
                core={"sport":sport,"event_id":ident[0],"book":ident[1],"market":ident[2],"original_threshold":ident[3],"event_start_utc":d["start"].isoformat(),"decision_captured_at_utc":d["captured_at"].isoformat(),"close_captured_at_utc":c["captured_at"].isoformat(),"decision_rows":d["rows"],"close_rows":c["rows"]}
                core["pair_sha256"]=hashlib.sha256(json.dumps(core,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest(); pairs.append(core); break
            if pairs and pairs[-1]["event_id"]==ident[0] and pairs[-1]["market"]==ident[2] and pairs[-1]["original_threshold"]==ident[3]: break
    return {"contract":"SPORTSEDGE_DIRECT_DK_FORWARD_PAIR_REPORT_V1","sport":sport,"status":"FORWARD_PAIRS_AVAILABLE" if pairs else "NO_ADMISSIBLE_FORWARD_PAIRS","pair_count":len(pairs),"pairs":pairs,"model_p_created":False,"truth_gate_pass_granted":False,"promotion_authority":False,"official_status_granted":False}

def load_ndjson(paths: Iterable[Path]) -> list[dict[str,Any]]:
    out=[]
    for path in paths:
        for line in path.read_text().splitlines():
            if line.strip(): out.append(json.loads(line))
    return out
