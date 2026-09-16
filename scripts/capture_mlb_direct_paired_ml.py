#!/usr/bin/env python3
"""Keyless MLB paired moneyline forward capture (FORWARD_CAPTURE_PARTIAL lane).

Persists exact two-sided DraftKings moneyline observations taken strictly before
event start, using the direct-web transport. No API credentials are used.

Grants no promotion authority. Writes nothing to config/deployments.json and does
not read or modify the frozen 3% moneyline edge floor. Every retained row is
stamped evidence_disposition=FORWARD_CAPTURE_PARTIAL: it can prove transport, PIT
chronology, identity binding, persistence and settlement mechanics, and it is
explicitly insufficient for Truth Gate promotion.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping
from sportsedge.direct_web_capture_source import DirectCaptureError, acquire_board, now_utc as _now, parse_iso as _parse
from sportsedge.draftkings_game_market_source import RawDraftKingsBoard, normalize_board
SPORT_KEY="baseball_mlb"; EVIDENCE_DISPOSITION="FORWARD_CAPTURE_PARTIAL"; SOURCE_CLASS="DRAFTKINGS_DIRECT_WEB_V1"; DEFAULT_OUTPUT_DIR="data/mlb_forward_capture"
CAPTURE_WINDOWS=(("T60",45.0,75.0),("T30",20.0,45.0),("T10",0.0,20.0))
def window_for(minutes_before: float):
    for label,low,high in CAPTURE_WINDOWS:
        if low < minutes_before <= high: return label
    return None
class CaptureBlocked(RuntimeError):
    def __init__(self,reason,detail=None): super().__init__(reason); self.reason=reason; self.detail=detail
def _artifact_sha(binder):
    try: return binder()
    except Exception as exc: raise CaptureBlocked("BLOCKED_ARTIFACT",str(exc)) from exc
def paired_moneylines(transport: Mapping[str,Any]):
    observed=_parse(transport["observed_at_utc"])
    board=RawDraftKingsBoard(transport["sport_key"],transport["source_uri"],b"",observed,transport["raw_payload"])
    by_event={}
    for row in normalize_board(board):
        if row.get("market")=="h2h": by_event.setdefault(str(row["provider_event_id"]),[]).append(row)
    raw_events={str(ev["id"]):ev for ev in transport["raw_payload"].get("events",[]) if isinstance(ev,Mapping) and ev.get("id") is not None}
    out=[]; anomalies=[]; in_window=0
    for event_id,ev in sorted(raw_events.items()):
        try: start=_parse(ev.get("startEventDate"))
        except Exception: continue
        if not observed < start: continue
        minutes_before=(start-observed).total_seconds()/60.0; window=window_for(minutes_before)
        if window is None: continue
        in_window += 1; rows=by_event.get(event_id,[])
        if not rows:
            anomalies.append({"provider_event_id":event_id,"capture_window":window,"reason":"NO_TWO_SIDED_MONEYLINE_NORMALIZED"}); continue
        first=rows[0]; home=next((r for r in rows if r["outcome"]==first["home_team"]),None); away=next((r for r in rows if r["outcome"]==first["away_team"]),None)
        if len(rows)!=2 or home is None or away is None:
            anomalies.append({"provider_event_id":event_id,"capture_window":window,"reason":"NOT_EXACTLY_TWO_SIDED","sides_seen":len(rows)}); continue
        out.append({"evidence_disposition":EVIDENCE_DISPOSITION,"promotion_authority":False,"source_class":SOURCE_CLASS,"sportsbook":"draftkings","provider":transport["provider"],"sport_key":transport["sport_key"],"provider_event_id":event_id,"home_team":first["home_team"],"away_team":first["away_team"],"scheduled_start_utc":first["commence_time"],"observed_at_utc":transport["observed_at_utc"],"capture_window":window,"minutes_before_start":round(minutes_before,2),"pit_basis":"OBSERVED_AT_UTC_VS_SCHEDULED_START_UTC","quote_side_skew_seconds":0,"quote_synchronization":"SINGLE_PAYLOAD_BOTH_SIDES","quote_synchronization_note":"Structural same-payload synchronization: both sides arrived in one response. This is NOT two independently timestamped quotes measured at zero seconds of skew.","book_last_update":None,"provider_quote_timestamp_available":False,"moneyline":{"status":"OK","home_price_american":home["price_american"],"away_price_american":away["price_american"]}})
    return {"rows":out,"anomalies":anomalies,"in_window":in_window,"events_on_board":len(raw_events)}
def capture(*,output_dir=DEFAULT_OUTPUT_DIR,clock:Callable[[],datetime]=_now,fetch=None,artifact_binder=None):
    if artifact_binder is None:
        from sportsedge.mlb_model_artifact import mlb_model_artifact_sha256
        artifact_binder=mlb_model_artifact_sha256
    artifact_sha=_artifact_sha(artifact_binder); kwargs={}
    if fetch is not None: kwargs["fetcher"]=fetch
    try: transport=acquire_board(SPORT_KEY,**kwargs)
    except DirectCaptureError as exc: raise CaptureBlocked("BLOCKED_TRANSPORT",getattr(exc,"attempts",None)) from exc
    scan=paired_moneylines(transport)
    if scan["anomalies"]: raise CaptureBlocked("BLOCKED_ONE_SIDED",{"anomalies":scan["anomalies"]})
    observed=_parse(transport["observed_at_utc"]); slate=observed.date().isoformat(); written=[]; skipped_existing=[]; base=Path(output_dir)/slate
    for row in scan["rows"]:
        key=f"{row['provider_event_id']}__{row['capture_window']}"; path=base/f"{key}.json"
        if path.exists(): skipped_existing.append(key); continue
        record={**row,"model_artifact_sha256":artifact_sha,"model_artifact_grants_promotion":False,"raw_sha256":transport["raw_sha256"],"source_uri":transport["source_uri"],"transport_host":transport["transport_host"],"attempts":transport["attempts"],"adapter_module_sha256":transport["adapter_module_sha256"],"capture_module_sha256":_self_sha(),"captured_at_utc":transport["observed_at_utc"]}
        path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(record,indent=2,sort_keys=True)); written.append(str(path))
    if not written:
        return {"status":"ALREADY_CAPTURED" if skipped_existing else "NO_CAPTURE_DUE","evidence_disposition":EVIDENCE_DISPOSITION,"slate_date":slate,"observations_retained":0,"already_present":skipped_existing,"events_on_board":scan["events_on_board"],"events_in_window":scan["in_window"],"paths":[],"raw_sha256":transport["raw_sha256"],"model_artifact_sha256":artifact_sha}
    return {"status":"RETAINED","evidence_disposition":EVIDENCE_DISPOSITION,"slate_date":slate,"observations_retained":len(written),"already_present":skipped_existing,"paths":written,"raw_sha256":transport["raw_sha256"],"model_artifact_sha256":artifact_sha}
def _self_sha():
    import hashlib
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument("--output-dir",default=DEFAULT_OUTPUT_DIR); args=ap.parse_args(argv)
    try: result=capture(output_dir=args.output_dir)
    except CaptureBlocked as exc:
        print(json.dumps({"status":"BLOCKED","reason":exc.reason,"detail":exc.detail,"evidence_disposition":EVIDENCE_DISPOSITION,"promotion_authority":False},indent=2)); return 2
    print(json.dumps(result,indent=2)); return 0
if __name__=="__main__": sys.exit(main())
