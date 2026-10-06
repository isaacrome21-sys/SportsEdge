"""Temporal validation gate for MLB context run-adjustment candidates."""
from __future__ import annotations
from math import sqrt
from typing import Any, Iterable, Mapping

VALIDATION_VERSION="mlb_context_temporal_validation_v1"
MIN_HOLDOUT_GAMES=200

def _rmse(rows: Iterable[Mapping[str,Any]], key: str) -> float:
    vals=[]
    for r in rows:
        try: vals.append((float(r[key])-float(r["actual_total_runs"]))**2)
        except (KeyError,TypeError,ValueError): continue
    return sqrt(sum(vals)/len(vals)) if vals else float("inf")

def validate_candidate(rows: list[Mapping[str,Any]], *, train_end: str, holdout_start: str, max_rmse_regression: float=0.0) -> dict[str,Any]:
    # Caller supplies PIT-built rows. This gate refuses overlapping train/holdout windows.
    if not train_end or not holdout_start or train_end >= holdout_start:
        raise ValueError("temporal holdout must begin after training window")
    hold=[r for r in rows if str(r.get("game_date","")) >= holdout_start]
    base=_rmse(hold,"baseline_total_runs")
    cand=_rmse(hold,"candidate_total_runs")
    enough=len(hold) >= MIN_HOLDOUT_GAMES
    passed=enough and cand <= base + float(max_rmse_regression)
    return {
      "validation_version":VALIDATION_VERSION,"train_end":train_end,"holdout_start":holdout_start,
      "holdout_games":len(hold),"minimum_holdout_games":MIN_HOLDOUT_GAMES,
      "baseline_rmse":base,"candidate_rmse":cand,"rmse_delta":cand-base,
      "status":"VALIDATED" if passed else "REJECTED",
    }

