"""Reused-history validation for NBA_LOCATION_SYMMETRIC_RIDGE_G1."""
from __future__ import annotations

from math import sqrt
from typing import Iterable, Sequence

from .location_symmetric_g1 import (
    DEFAULT_ALPHA_GRID,
    fit_nba_location_symmetric_g1,
    season_end_year,
    select_alpha,
)
from .pace_efficiency import fit_pace_efficiency, predict_state
from .training import NBATrainingRow

SCHEMA = "NBA_LOCATION_SYMMETRIC_G1_DEVELOPMENT_VALIDATION_V1"
TARGET_TEST_SEASONS = (2021, 2022, 2023, 2024, 2025)


def _actual(row: NBATrainingRow, target: str) -> float:
    return float(row.home_points - row.away_points) if target == "margin" else float(row.home_points + row.away_points)


def _metrics(pred: Sequence[float], actual: Sequence[float]) -> dict:
    if len(pred) != len(actual) or not pred:
        raise ValueError("NBA_LOCATION_G1_METRICS_ALIGNMENT_INVALID")
    e = [p - a for p, a in zip(pred, actual)]
    return {"n": len(e), "rmse": sqrt(sum(x * x for x in e) / len(e)), "mae": sum(abs(x) for x in e) / len(e)}


def _baseline_predict(model, row: NBATrainingRow) -> tuple[float, float]:
    p = predict_state(model, row)
    home = p["expected_possessions"] * p["home_points_per_100"] / 100.0
    away = p["expected_possessions"] * p["away_points_per_100"] / 100.0
    return home - away, home + away


def validate_nba_location_symmetric_g1(
    rows: Iterable[NBATrainingRow],
    *,
    alpha_grid=DEFAULT_ALPHA_GRID,
) -> dict:
    data = tuple(sorted(rows, key=lambda r: (r.tipoff, r.game_id)))
    available = {season_end_year(r) for r in data}
    test_seasons = tuple(s for s in TARGET_TEST_SEASONS if s in available)
    if len(test_seasons) < 3:
        raise ValueError("NBA_LOCATION_G1_AT_LEAST_THREE_OUTER_FOLDS_REQUIRED")

    folds = []
    aggregate = {target: {"candidate": [], "baseline": [], "actual": []} for target in ("margin", "total")}
    for test_season in test_seasons:
        train = tuple(r for r in data if season_end_year(r) < test_season)
        test = tuple(r for r in data if season_end_year(r) == test_season)
        if len({season_end_year(r) for r in train}) < 3 or not test:
            continue
        ms = select_alpha(train, target="margin", alpha_grid=alpha_grid)
        ts = select_alpha(train, target="total", alpha_grid=alpha_grid)
        candidate = fit_nba_location_symmetric_g1(train, margin_alpha=ms["selected_alpha"], total_alpha=ts["selected_alpha"])
        baseline = fit_pace_efficiency(train)

        cm=[]; ct=[]; bm=[]; bt=[]; am=[]; at=[]
        for row in test:
            m,t = candidate.predict(row)
            b_m,b_t = _baseline_predict(baseline,row)
            cm.append(m); ct.append(t); bm.append(b_m); bt.append(b_t)
            am.append(_actual(row,"margin")); at.append(_actual(row,"total"))
        fold = {
            "test_season": test_season,
            "train_seasons": sorted({season_end_year(r) for r in train}),
            "alpha_selection": {"margin": ms, "total": ts},
            "margin": {"candidate": _metrics(cm,am), "baseline": _metrics(bm,am)},
            "total": {"candidate": _metrics(ct,at), "baseline": _metrics(bt,at)},
        }
        for target in ("margin","total"):
            fold[target]["candidate_beats_baseline_rmse"] = fold[target]["candidate"]["rmse"] < fold[target]["baseline"]["rmse"]
            fold[target]["candidate_beats_baseline_mae"] = fold[target]["candidate"]["mae"] < fold[target]["baseline"]["mae"]
        folds.append(fold)
        for key,values in (("candidate",cm),("baseline",bm),("actual",am)): aggregate["margin"][key].extend(values)
        for key,values in (("candidate",ct),("baseline",bt),("actual",at)): aggregate["total"][key].extend(values)

    if len(folds) < 3:
        raise ValueError("NBA_LOCATION_G1_AT_LEAST_THREE_OUTER_FOLDS_REQUIRED")
    summary={}
    required=len(folds)//2+1
    for target in ("margin","total"):
        cand=_metrics(aggregate[target]["candidate"],aggregate[target]["actual"])
        base=_metrics(aggregate[target]["baseline"],aggregate[target]["actual"])
        rw=sum(bool(f[target]["candidate_beats_baseline_rmse"]) for f in folds)
        mw=sum(bool(f[target]["candidate_beats_baseline_mae"]) for f in folds)
        passed=rw>=required and mw>=required and cand["rmse"]<base["rmse"] and cand["mae"]<base["mae"]
        summary[target]={"candidate":cand,"baseline":base,"rmse_fold_wins":rw,"mae_fold_wins":mw,"required_fold_wins":required,"passed":passed}
    overall=summary["margin"]["passed"] and summary["total"]["passed"]
    return {
        "schema":SCHEMA,
        "candidate_family":"NBA_LOCATION_SYMMETRIC_RIDGE_G1",
        "evidence_role":"REUSED_RESEARCH_HISTORY_NOT_UNTOUCHED_PROMOTION_EVIDENCE",
        "folds":folds,
        "summary":summary,
        "location_gate_pass":overall,
        "authority":{"research_only":True,"model_p":False,"promotion":False,"staking":False,"official":False},
    }


__all__=["SCHEMA","TARGET_TEST_SEASONS","validate_nba_location_symmetric_g1"]
