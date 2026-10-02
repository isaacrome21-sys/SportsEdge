"""Fail-closed structural gate math for the isolated NFL possession challenger.

This module performs no data acquisition and does not open the frozen 2024-2025
holdout. It only emits/scorers already-materialized simulated and empirical
metrics against the preregistered bands in ``NFL_UNIFIED_MARKET_PROBABILITY_CONTRACT.md``.
Passing this scorer is research evidence only; it grants no Model_P, promotion,
staking, Truth-Gate, or OFFICIAL authority.
"""
from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from numbers import Real
from typing import Any

import numpy as np

from .nfl_possession_challenger import (
    VectorizedPossessionChallengerBaseline,
    VectorizedSummary,
)

DRIVE_OUTCOMES=("TD","FG","PUNT","TURNOVER","DOWNS","END_HALF_GAME")
TOTAL_QUANTILES=("10","25","50","75","90")
LATE_GAME_BUCKETS=("leading","trailing")


def _number(value: Any, name: str) -> float:
    if isinstance(value,bool) or not isinstance(value,Real) or not isfinite(float(value)):
        raise ValueError(f"CHALLENGER_STRUCTURAL_METRIC_INVALID:{name}")
    return float(value)


def _rate(value: Any, name: str) -> float:
    result=_number(value,name)
    if not 0.0<=result<=1.0:
        raise ValueError(f"CHALLENGER_STRUCTURAL_RATE_OUT_OF_RANGE:{name}")
    return result


def _mapping(parent: Mapping[str,Any], key: str) -> Mapping[str,Any]:
    value=parent.get(key)
    if not isinstance(value,Mapping):
        raise ValueError(f"CHALLENGER_STRUCTURAL_MAPPING_REQUIRED:{key}")
    return value


def _row(name: str, simulated: float, empirical: float, tolerance: float) -> dict[str,Any]:
    error=abs(simulated-empirical)
    return {
        "metric":name,
        "simulated":simulated,
        "empirical":empirical,
        "absolute_error":error,
        "tolerance":tolerance,
        "disposition":"PASS" if error<=tolerance else "FAIL",
    }


def summarize_vectorized_structural_metrics(summary: VectorizedSummary) -> dict[str,Any]:
    """Emit only structural metrics represented by the current vectorized paths.

    This deliberately does not invent opening-drive, first-score or late-game
    metrics. They remain explicit blockers until the simulator/source carries
    the required state. Quantiles use NumPy's frozen ``linear`` method.
    """
    if not isinstance(summary,VectorizedSummary):
        raise TypeError("VECTORIZED_CHALLENGER_SUMMARY_REQUIRED")
    n=len(summary.margins)
    if n<=0:
        raise ValueError("CHALLENGER_STRUCTURAL_PATHS_EMPTY")
    arrays=(
        summary.totals,summary.home_possessions,summary.away_possessions,
        summary.overtime_possessions,
    )
    if any(getattr(values,"shape",None)!=(n,) for values in arrays):
        raise ValueError("CHALLENGER_SUMMARY_ROW_MISMATCH")
    counts=summary.outcome_counts
    expected=len(VectorizedPossessionChallengerBaseline.OUTCOMES)
    if getattr(counts,"shape",None)!=(n,expected):
        raise ValueError("CHALLENGER_OUTCOME_COUNT_SHAPE_INVALID")
    numeric=(summary.margins,)+arrays+(counts,)
    if any(getattr(values,"dtype",None) is None or values.dtype.kind not in "iuf" for values in numeric):
        raise ValueError("CHALLENGER_STRUCTURAL_ARRAY_INVALID")
    if any(not np.all(np.isfinite(values)) for values in numeric):
        raise ValueError("CHALLENGER_STRUCTURAL_ARRAY_INVALID")
    if np.any(counts<0) or np.any(counts!=np.floor(counts)):
        raise ValueError("CHALLENGER_OUTCOME_COUNT_INVALID")
    outcome_total=float(np.sum(counts))
    if outcome_total<=0:
        raise ValueError("CHALLENGER_DRIVE_OUTCOMES_EMPTY")

    indexes={str(name):i for i,name in enumerate(VectorizedPossessionChallengerBaseline.OUTCOMES)}
    outcome_key={
        "TD":"TD","FG":"FG","PUNT":"PUNT","TURNOVER":"TURNOVER",
        "DOWNS":"DOWNS","END_HALF_GAME":"END_HALF",
    }
    shares={
        public:float(np.sum(counts[:,indexes[internal]])/outcome_total)
        for public,internal in outcome_key.items()
    }
    quantiles=np.quantile(summary.totals,[.10,.25,.50,.75,.90],method="linear")
    metrics={
        "mean_possessions_per_team_game":float(np.mean(summary.home_possessions+summary.away_possessions)/2.0),
        "drive_outcome_shares":shares,
        "absolute_margin_mass":{
            str(k):float(np.mean(np.abs(summary.margins)==k)) for k in (3,7,10)
        },
        "mean_total_points":float(np.mean(summary.totals)),
        "total_point_quantiles":{
            key:float(value) for key,value in zip(TOTAL_QUANTILES,quantiles)
        },
    }
    return {
        "schema":"NFL_CHALLENGER_SUPPORTED_STRUCTURAL_METRICS_V1",
        "path_count":n,
        "quantile_method":"numpy_linear",
        "metrics":metrics,
        "missing_required_metrics":[
            "opening_drive_scoring_rate",
            "first_score_opening_receiver_rate",
            "late_game.leading.fourth_down_attempt_rate",
            "late_game.leading.pace_proxy_rate",
            "late_game.trailing.fourth_down_attempt_rate",
            "late_game.trailing.pace_proxy_rate",
        ],
        "authority":"NONE_RESEARCH_ONLY",
        "promotion_authority":False,
        "truth_gate_authority":False,
        "staking_authority":False,
        "official_authority":False,
    }


def score_challenger_structural_metrics(
    simulated: Mapping[str,Any], empirical: Mapping[str,Any]
) -> dict[str,Any]:
    """Score the frozen structural bands without acquiring or selecting data.

    Expected rates are fractions, not percentages. Sparse required late-game
    empirical buckets (<200 possessions) are reported ``INSUFFICIENT_SAMPLE``
    and block the aggregate status exactly as preregistered; they are never
    silently pooled or dropped.
    """
    if not isinstance(simulated,Mapping) or not isinstance(empirical,Mapping):
        raise TypeError("CHALLENGER_STRUCTURAL_MAPPING_REQUIRED")

    rows=[]
    rows.append(_row(
        "mean_possessions_per_team_game",
        _number(simulated.get("mean_possessions_per_team_game"),"mean_possessions_per_team_game.simulated"),
        _number(empirical.get("mean_possessions_per_team_game"),"mean_possessions_per_team_game.empirical"),
        .50,
    ))
    rows.append(_row(
        "opening_drive_scoring_rate",
        _rate(simulated.get("opening_drive_scoring_rate"),"opening_drive_scoring_rate.simulated"),
        _rate(empirical.get("opening_drive_scoring_rate"),"opening_drive_scoring_rate.empirical"),
        .03,
    ))
    rows.append(_row(
        "first_score_opening_receiver_rate",
        _rate(simulated.get("first_score_opening_receiver_rate"),"first_score_opening_receiver_rate.simulated"),
        _rate(empirical.get("first_score_opening_receiver_rate"),"first_score_opening_receiver_rate.empirical"),
        .03,
    ))

    simulated_outcomes=_mapping(simulated,"drive_outcome_shares")
    empirical_outcomes=_mapping(empirical,"drive_outcome_shares")
    for outcome in DRIVE_OUTCOMES:
        rows.append(_row(
            f"drive_outcome_share.{outcome}",
            _rate(simulated_outcomes.get(outcome),f"drive_outcome_shares.{outcome}.simulated"),
            _rate(empirical_outcomes.get(outcome),f"drive_outcome_shares.{outcome}.empirical"),
            .03,
        ))

    simulated_margins=_mapping(simulated,"absolute_margin_mass")
    empirical_margins=_mapping(empirical,"absolute_margin_mass")
    for margin,tolerance in (("3",.02),("7",.02),("10",.015)):
        rows.append(_row(
            f"absolute_margin_mass.{margin}",
            _rate(simulated_margins.get(margin),f"absolute_margin_mass.{margin}.simulated"),
            _rate(empirical_margins.get(margin),f"absolute_margin_mass.{margin}.empirical"),
            tolerance,
        ))

    rows.append(_row(
        "mean_total_points",
        _number(simulated.get("mean_total_points"),"mean_total_points.simulated"),
        _number(empirical.get("mean_total_points"),"mean_total_points.empirical"),
        2.0,
    ))

    simulated_quantiles=_mapping(simulated,"total_point_quantiles")
    empirical_quantiles=_mapping(empirical,"total_point_quantiles")
    for quantile in TOTAL_QUANTILES:
        rows.append(_row(
            f"total_point_quantile.{quantile}",
            _number(simulated_quantiles.get(quantile),f"total_point_quantiles.{quantile}.simulated"),
            _number(empirical_quantiles.get(quantile),f"total_point_quantiles.{quantile}.empirical"),
            3.0,
        ))

    simulated_late=_mapping(simulated,"late_game")
    empirical_late=_mapping(empirical,"late_game")
    for bucket in LATE_GAME_BUCKETS:
        sim_bucket=_mapping(simulated_late,bucket)
        emp_bucket=_mapping(empirical_late,bucket)
        sample=emp_bucket.get("sample_count")
        if isinstance(sample,bool) or not isinstance(sample,int) or sample<0:
            raise ValueError(f"CHALLENGER_STRUCTURAL_SAMPLE_COUNT_INVALID:{bucket}")
        if sample<200:
            for metric in ("fourth_down_attempt_rate","pace_proxy_rate"):
                rows.append({
                    "metric":f"late_game.{bucket}.{metric}",
                    "simulated":None,
                    "empirical":None,
                    "absolute_error":None,
                    "tolerance":.05,
                    "empirical_sample_count":sample,
                    "disposition":"INSUFFICIENT_SAMPLE",
                })
            continue
        for metric in ("fourth_down_attempt_rate","pace_proxy_rate"):
            row=_row(
                f"late_game.{bucket}.{metric}",
                _rate(sim_bucket.get(metric),f"late_game.{bucket}.{metric}.simulated"),
                _rate(emp_bucket.get(metric),f"late_game.{bucket}.{metric}.empirical"),
                .05,
            )
            row["empirical_sample_count"]=sample
            rows.append(row)

    passed=all(row["disposition"]=="PASS" for row in rows)
    return {
        "schema":"NFL_CHALLENGER_STRUCTURAL_GATE_V1",
        "status":"PASS" if passed else "BLOCKED",
        "authority":"NONE_RESEARCH_ONLY",
        "promotion_authority":False,
        "truth_gate_authority":False,
        "staking_authority":False,
        "official_authority":False,
        "metrics":rows,
    }
