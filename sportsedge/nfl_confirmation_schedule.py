"""Schedule-completeness guard for NFL confirmation captures."""
from __future__ import annotations
import csv, hashlib, json, os
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from zoneinfo import ZoneInfo
SCHEDULE_ENV="NFL_SCHEDULE_CSV"; SCHEDULE_SOURCE="nflverse/nfldata data/games.csv"; SEASON=2026
class ScheduleExpectationError(RuntimeError): pass
@dataclass(frozen=True)
class ScheduleSnapshot:
    path:str; sha256:str; rows:tuple[dict[str,str],...]
    def provenance(self): return {"source":SCHEDULE_SOURCE,"sha256":self.sha256,"matching_semantics":"KICKOFF_UTC_MULTIPLICITY"}
def iso_z(dt):
    if dt.tzinfo is None or dt.utcoffset() is None: raise ScheduleExpectationError("SCHEDULE_TIME_NAIVE")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
def load_snapshot(path=None):
    raw_path=str(path or os.environ.get(SCHEDULE_ENV,"")).strip()
    if not raw_path: raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_REQUIRED")
    target=Path(raw_path)
    if not target.is_file(): raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_MISSING")
    raw=target.read_bytes()
    with target.open(newline="",encoding="utf-8-sig") as h: rows=tuple(dict(r) for r in csv.DictReader(h))
    if not rows: raise ScheduleExpectationError("NFL_SCHEDULE_SNAPSHOT_EMPTY")
    return ScheduleSnapshot(str(target),hashlib.sha256(raw).hexdigest(),rows)
def schedule_kickoff_utc(row):
    if str(row.get("season") or "") != str(SEASON): return None
    gd=str(row.get("gameday") or "").strip(); gt=str(row.get("gametime") or "").strip()
    if not gd or not gt:return None
    try:return datetime.fromisoformat(f"{gd}T{gt}").replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except ValueError:return None
def week_of(kickoff,cfg): return (kickoff.astimezone(ZoneInfo(str(cfg["timezone"]))).date()-date.fromisoformat(str(cfg["week1_tuesday_local_date"]))).days//7+1
def opener_expected_kickoffs(cfg,week,snapshot):
    expected=Counter()
    for row in snapshot.rows:
        k=schedule_kickoff_utc(row)
        if k is not None and week_of(k,cfg)==int(week): expected[iso_z(k)]+=1
    if not expected: raise ScheduleExpectationError(f"NFL_OPENER_SCHEDULE_EMPTY:week={week}")
    return expected
def _record_admissible(record,cfg):
    if record.get("capture_kind")!="FINAL" or record.get("book")!=cfg.get("bookmaker") or record.get("source_class") not in (cfg.get("source_priority") or []) or not record.get("retrieved_at_utc"): return False
    if not isinstance(record.get("hashes"),Mapping) or not record["hashes"]: return False
    if cfg.get("schedule_coverage_semantics"):
        s=record.get("schedule")
        if not isinstance(s,Mapping) or s.get("matching_semantics")!="KICKOFF_UTC_MULTIPLICITY" or not s.get("sha256"): return False
    games=record.get("games")
    return isinstance(games,list) and bool(games) and all(isinstance(g,Mapping) and isinstance(g.get("spread"),Mapping) and g["spread"].get("status")=="OK" and isinstance(g.get("total"),Mapping) and g["total"].get("status")=="OK" for g in games)
def _records(cfg):
    for p in Path(str(cfg["output_dir"])).glob("week*/final/*.json"):
        try:r=json.loads(p.read_text())
        except (OSError,json.JSONDecodeError):continue
        if isinstance(r,Mapping) and _record_admissible(r,cfg):yield r
def captured_final_kickoffs(cfg):
    c=Counter()
    for r in _records(cfg):
        for g in r.get("games") or []:
            try:c[iso_z(datetime.fromisoformat(str(g.get("commence_time") or "").replace("Z","+00:00")))]+=1
            except ValueError:pass
    return c
def captured_final_event_ids(cfg): return {str(g.get("event_id")) for r in _records(cfg) for g in (r.get("games") or []) if str(g.get("event_id") or "").strip()}
def final_expected_due_kickoffs(cfg,now,snapshot):
    if now.tzinfo is None or now.utcoffset() is None: raise ScheduleExpectationError("NFL_FINAL_NOW_NAIVE")
    now=now.astimezone(timezone.utc); lead=timedelta(minutes=int(cfg["final_minutes_before_kickoff"])); width=timedelta(minutes=int(cfg["final_window_minutes"])); expected=Counter()
    for row in snapshot.rows:
        k=schedule_kickoff_utc(row)
        if k is None or week_of(k,cfg)<int(cfg["first_week"]):continue
        start=k-lead; end=min(start+width,k)
        if start<=now<end: expected[iso_z(k)]+=1
    captured=captured_final_kickoffs(cfg); return Counter({z:max(0,n-captured[z]) for z,n in expected.items() if n>captured[z]})
def capture_kickoff_counts(rows):
    c=Counter()
    for row in rows:
        raw=str(row.get("commence_time") or "").strip()
        if not raw:raise ScheduleExpectationError("CAPTURE_ROW_KICKOFF_MISSING")
        try:k=datetime.fromisoformat(raw.replace("Z","+00:00"))
        except ValueError as exc:raise ScheduleExpectationError("CAPTURE_ROW_KICKOFF_INVALID") from exc
        c[iso_z(k)]+=1
    return c
def require_exact_coverage(rows:Sequence[Mapping[str,object]],expected:Counter[str],*,kind:str):
    actual=capture_kickoff_counts(rows)
    if actual!=expected: raise ScheduleExpectationError("NFL_SCHEDULE_COVERAGE_MISMATCH:"+json.dumps({"kind":kind,"expected":dict(sorted(expected.items())),"actual":dict(sorted(actual.items()))},sort_keys=True,separators=(",",":")))
