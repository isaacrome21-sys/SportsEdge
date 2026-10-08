#!/usr/bin/env python3
"""Print a fail-closed research-only readout of create-only pitcher receipts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from sportsedge.mlb_postseason_k_outs_forward_readout import readout


def main()->int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    try:
        result=readout(args.root/"predictions",args.root/"settlements")
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf8")
        print(json.dumps({"status":result["status"],
                          "independent_games":result["independent_games"],
                          "complete_pitcher_games":result["complete_pitcher_games"],
                          "betting_card_eligible":result["betting_card_eligible"]},sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"BLOCKED","reason":str(exc)}))
        return 2


if __name__=="__main__":
    sys.exit(main())
