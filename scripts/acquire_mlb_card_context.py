#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,sys
from datetime import datetime,timezone
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sportsedge.mlb_run_it_pregame import acquire_mlb_run_it_pregame
def game_pks(payload):
 found=[]; games=payload.get("games") or ([{"resolved_game":payload.get("resolved_game")}] if payload.get("resolved_game") else [])
 for g in games:
  pk=(g.get("resolved_game") or {}).get("game_pk")
  if pk is not None and int(pk) not in found:found.append(int(pk))
 for row in payload.get("coverage_slots") or []:
  try:pk=int(row.get("game_id"))
  except (TypeError,ValueError):continue
  if pk>0 and pk not in found:found.append(pk)
 for row in payload.get("results") or []:
  try:pk=int(row.get("game_id"))
  except (TypeError,ValueError):continue
  if pk>0 and pk not in found:found.append(pk)
 return found
def main(argv=None,*,acquire=acquire_mlb_run_it_pregame):
 ap=argparse.ArgumentParser();ap.add_argument("--engine-output",default="artifacts/manual_mlb_snapshot_card.json");ap.add_argument("--out-dir",default="artifacts/mlb_context");args=ap.parse_args(argv)
 payload=json.loads(Path(args.engine_output).read_text());out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True);failures=[]
 for pk in game_pks(payload):
  now=datetime.now(timezone.utc)
  try:bundle=acquire(game_pk=pk,as_of=now)
  except Exception as exc:failures.append(f"Game {pk}: context NOT RETRIEVED ({type(exc).__name__}: {exc})");continue
  (out/f"{pk}.json").write_text(json.dumps(bundle,indent=2,default=str));print(f"{pk}: {bundle.get('status')} {str(bundle.get('payload_sha256'))[:12]}")
 (out/"failures.json").write_text(json.dumps(failures,indent=2))
 for f in failures:print(f)
 return 0
if __name__=="__main__":raise SystemExit(main())
