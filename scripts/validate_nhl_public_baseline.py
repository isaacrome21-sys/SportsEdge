#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path

from scripts.fit_nhl_public_baseline import _load_games
from sportsedge.sports.nhl.public_baseline_validation import validate_public_baseline


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True,type=Path)
    p.add_argument("--output",required=True,type=Path)
    p.add_argument("--fit-before",default="2025-07-01T00:00:00+00:00")
    p.add_argument("--validate-start",default="2025-10-01T00:00:00+00:00")
    p.add_argument("--validate-before",default="2026-05-01T00:00:00+00:00")
    p.add_argument("--min-team-games",type=int,default=10)
    p.add_argument("--ridge",type=float,default=1.0)
    p.add_argument("--version",default="nhl-public-boxscore-baseline-v1")
    a=p.parse_args()
    result=validate_public_baseline(
        _load_games(a.input),
        fit_before=a.fit_before,
        validate_start=a.validate_start,
        validate_before=a.validate_before,
        min_team_games=a.min_team_games,
        ridge=a.ridge,
        version=a.version,
    )
    payload={
        "schema":"NHL_PUBLIC_BASELINE_VALIDATION_RESULT_V1",
        "training_rows":result.training_rows,
        "validation_rows":result.validation_rows,
        "team_goal_mae":result.team_goal_mae,
        "team_goal_rmse":result.team_goal_rmse,
        "poisson_negative_log_likelihood":result.poisson_negative_log_likelihood,
        "mean_predicted_regulation_goals":result.mean_predicted_regulation_goals,
        "mean_actual_regulation_goals":result.mean_actual_regulation_goals,
        "artifact":result.artifact.as_json_dict(),
        "evidence_role":result.evidence_role,
        "authority":{"research_only":True,"model_p":False,"truth_gate":False,"staking":False,"official":False},
    }
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(payload,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
