#!/usr/bin/env python3
"""Run frozen V2G research decisions at the confirmation opener and exact-threshold closes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.sports.nfl.odds_source import fetch_nfl_odds
from sportsedge.sports.nfl.v2g_forward_clv import build_decisions, grade_close, validate_policy

KEY_NAMES=("SPORTSEDGE_ODDS_API_KEY","SPORTSEDGE_ODDS_API_KEY_2","SPORTSEDGE_ODDS_API_KEY_3","SPORTSEDGE_ODDS_API_KEY_4")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_first(path: Path, payload) -> bool:
    text=json.dumps(payload,indent=2,sort_keys=True)+"\n"
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        return False
    path.write_text(text,encoding="utf-8")
    return True


def _week_number(path: Path) -> int:
    raw=path.name
    if not raw.startswith("week") or not raw[4:].isdigit():
        raise ValueError(f"NFL_V2G_FORWARD_WEEK_DIR_INVALID:{raw}")
    return int(raw[4:])


def materialize_decisions(*, prediction_dir: Path, capture_root: Path, state_root: Path, policy_path: Path, code_git_sha: str) -> int:
    policy=_read(policy_path); validate_policy(policy); policy_sha=_sha(policy_path)
    created=0
    for week_dir in sorted(capture_root.glob("week*")):
        if not week_dir.is_dir(): continue
        week=_week_number(week_dir)
        if week < int(policy["first_eligible_week"]): continue
        opener_path=week_dir/"opener.json"
        if not opener_path.exists(): continue
        opener=_read(opener_path)
        for pred_path in sorted(prediction_dir.glob(f"2026_{week:02d}_*.json")):
            pred=_read(pred_path)
            out=state_root/f"week{week:02d}"/str(pred.get("game_id") or pred_path.stem)/"decision.json"
            if out.exists(): continue
            rows=build_decisions(pred,opener,policy,code_git_sha=code_git_sha)
            bundle={
                "schema_version":"SPORTSEDGE_NFL_V2G_FORWARD_DECISION_BUNDLE_V1",
                "game_id":pred["game_id"],"week":week,"policy_sha256":policy_sha,
                "prediction_path":str(pred_path),"prediction_file_sha256":_sha(pred_path),
                "opener_capture_path":str(opener_path),"opener_capture_file_sha256":_sha(opener_path),
                "rows":rows,"promotion_authority":False,"may_create_model_p":False,"official_status_granted":False,
            }
            created += int(_write_first(out,bundle))
    return created


def capture_due_closes(*, state_root: Path, policy_path: Path, now: datetime) -> tuple[int,int]:
    policy=_read(policy_path); validate_policy(policy)
    start=float(policy["close_capture"]["window_start_minutes_before_kickoff"])
    end=float(policy["close_capture"]["window_end_minutes_before_kickoff"])
    keys=[os.environ.get(name,"").strip() for name in KEY_NAMES if os.environ.get(name,"").strip()]
    captured=inconclusive=0
    for decision_path in sorted(state_root.glob("week*/*/decision.json")):
        game_dir=decision_path.parent
        if (game_dir/"clv.json").exists(): continue
        bundle=_read(decision_path); rows=bundle.get("rows") or []
        if not rows: raise ValueError(f"NFL_V2G_FORWARD_DECISION_ROWS_EMPTY:{decision_path}")
        if not any(r.get("gate_result")=="SHADOW_QUALIFIED" for r in rows): continue
        kickoff=datetime.fromisoformat(str(rows[0]["game_start_ts"])).astimezone(timezone.utc)
        minutes=(kickoff-now).total_seconds()/60.0
        if not (end <= minutes <= start): continue
        if not keys: raise RuntimeError("NFL_V2G_FORWARD_CLOSE_API_KEYS_MISSING")
        event_id=str(rows[0].get("provider_event_id") or "")
        result=fetch_nfl_odds(keys,event_id=event_id)
        event=result.value
        captured_at=datetime.now(timezone.utc)
        if captured_at >= kickoff: raise RuntimeError("NFL_V2G_FORWARD_CLOSE_FETCH_AFTER_KICKOFF")
        raw_bundle={
            "schema_version":"SPORTSEDGE_NFL_V2G_RAW_CLOSE_SNAPSHOT_V1","captured_at_utc":captured_at.isoformat(),
            "provider_event_id":event_id,"provider_event":event,"key_slot":result.key_slot,"prior_key_failures":len(result.failures),
        }
        _write_first(game_dir/"raw_close.json",raw_bundle)
        clv_rows=grade_close(rows,event,captured_at=captured_at.isoformat())
        clv_bundle={
            "schema_version":"SPORTSEDGE_NFL_V2G_FORWARD_CLV_BUNDLE_V1","game_id":bundle["game_id"],
            "decision_file_sha256":_sha(decision_path),"raw_close_file_sha256":_sha(game_dir/"raw_close.json"),
            "rows":clv_rows,"promotion_authority":False,"may_create_model_p":False,"official_status_granted":False,
        }
        _write_first(game_dir/"clv.json",clv_bundle)
        captured += 1
        if any(r.get("status","").startswith("INCONCLUSIVE") for r in clv_rows): inconclusive += 1
    return captured,inconclusive


def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--prediction-dir",type=Path,required=True)
    p.add_argument("--capture-root",type=Path,required=True)
    p.add_argument("--state-root",type=Path,required=True)
    p.add_argument("--policy",type=Path,required=True)
    p.add_argument("--code-git-sha",required=True)
    args=p.parse_args()
    now=datetime.now(timezone.utc)
    made=materialize_decisions(prediction_dir=args.prediction_dir,capture_root=args.capture_root,state_root=args.state_root,policy_path=args.policy,code_git_sha=args.code_git_sha)
    closed,inconclusive=capture_due_closes(state_root=args.state_root,policy_path=args.policy,now=now)
    print(json.dumps({"decision_bundles_created":made,"close_bundles_created":closed,"close_bundles_inconclusive":inconclusive,"checked_at_utc":now.isoformat()},sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
