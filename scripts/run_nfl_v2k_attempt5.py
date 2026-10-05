#!/usr/bin/env python3
"""Run NFL V2K Attempt-5 market-calibration validation."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge.sports.nfl import v2k_attempt1_validation as a1
from sportsedge.sports.nfl import v2k_attempt5_validation as v5

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--schedule",type=Path,required=True)
    ap.add_argument("--out",type=Path,required=True)
    args=ap.parse_args()
    contract=v5.preflight()
    schedule=a1.load_schedule(args.schedule)
    result=v5.evaluate(schedule,contract)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
