#!/usr/bin/env python3
"""Fit a market-blind NFL score-composition prior from pre-cutoff team-game rows."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from sportsedge.nfl_scoring_composition_fit import fit_scoring_composition_prior
from sportsedge.nfl_scoring_composition_artifact import dump_prior

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True,help="JSON array of completed team-game scoring rows")
    ap.add_argument("--as-of",required=True,help="PIT cutoff; every completed_at must be earlier")
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    rows=json.loads(Path(a.input).read_text(encoding="utf-8"))
    if not isinstance(rows,list): raise SystemExit("NFL_SCORING_PRIOR_INPUT_ARRAY_REQUIRED")
    prior=fit_scoring_composition_prior(rows,as_of=a.as_of)
    payload=dump_prior(prior)
    out=Path(a.output); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps({"status":"OK","training_rows":prior.training_rows,"artifact_sha256":payload["artifact_sha256"]},sort_keys=True))
    return 0
if __name__=="__main__": raise SystemExit(main())
