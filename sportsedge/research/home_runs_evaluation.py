"""Chronological evaluation for HOME_RUNS baseline/challenger/ablation arms."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from math import isfinite, log
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_ARMS = (
    "baseline_v01",
    "surge_haircut_v02",
    "platoon_v03",
    "park_weather_v03",
    "geometry_v03",
)


class HomeRunsEvaluationError(ValueError):
    pass


def _prob(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise HomeRunsEvaluationError(f"{field} must be probability")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HomeRunsEvaluationError(f"{field} must be probability") from exc
    if not isfinite(out) or not 0.0 < out < 1.0:
        raise HomeRunsEvaluationError(f"{field} must be in (0,1)")
    return out


def _outcome(value: Any) -> int:
    if value in (0, 0.0, False):
        return 0
    if value in (1, 1.0, True):
        return 1
    raise HomeRunsEvaluationError("outcome must be binary")


def _month(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError as exc:
        raise HomeRunsEvaluationError("game_date must be YYYY-MM-DD") from exc
    return f"{parsed.year:04d}-{parsed.month:02d}"


def _arm_metrics(rows: Sequence[Mapping[str, Any]], arm: str, bins: int) -> dict[str, Any]:
    scored: list[tuple[float, int]] = []
    for row in rows:
        value = row.get(arm)
        if value is None:
            continue
        scored.append((_prob(value, arm), _outcome(row.get("outcome"))))
    if not scored:
        return {"n": 0, "brier": None, "log_loss": None, "ece": None, "calibration_bins": []}
    n = len(scored)
    brier = sum((p - y) ** 2 for p, y in scored) / n
    log_loss = sum(-(y * log(p) + (1 - y) * log(1.0 - p)) for p, y in scored) / n

    buckets: list[dict[str, Any]] = []
    ece = 0.0
    for i in range(bins):
        lo = i / bins
        hi = (i + 1) / bins
        selected = [(p, y) for p, y in scored if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not selected:
            continue
        mean_p = sum(p for p, _ in selected) / len(selected)
        observed = sum(y for _, y in selected) / len(selected)
        weight = len(selected) / n
        ece += weight * abs(mean_p - observed)
        buckets.append({
            "lower": lo,
            "upper": hi,
            "n": len(selected),
            "mean_probability": mean_p,
            "observed_rate": observed,
            "absolute_error": abs(mean_p - observed),
        })
    return {
        "n": n,
        "brier": brier,
        "log_loss": log_loss,
        "ece": ece,
        "calibration_bins": buckets,
    }


def evaluate_home_run_arms(
    rows: Iterable[Mapping[str, Any]],
    *,
    arms: Sequence[str] = DEFAULT_ARMS,
    calibration_bins: int = 10,
) -> dict[str, Any]:
    """Evaluate identical settled observations overall and in chronological months.

    Missing arm probabilities are not imputed. Pairwise deltas are reported only on
    observations where both arms exist, preventing coverage differences from posing
    as model improvement.
    """
    if isinstance(calibration_bins, bool) or not 2 <= int(calibration_bins) <= 50:
        raise HomeRunsEvaluationError("calibration_bins must be in [2,50]")
    data = [dict(row) for row in rows]
    if not data:
        raise HomeRunsEvaluationError("evaluation rows required")
    for row in data:
        _outcome(row.get("outcome"))
        _month(row.get("game_date"))

    arm_list = tuple(str(arm) for arm in arms)
    overall = {
        arm: _arm_metrics(data, arm, int(calibration_bins))
        for arm in arm_list
    }

    paired: dict[str, Any] = {}
    references = ("baseline_v01", "surge_haircut_v02")
    for arm in arm_list:
        for reference in references:
            if arm == reference or reference not in arm_list:
                continue
            common = [
                row for row in data
                if row.get(arm) is not None and row.get(reference) is not None
            ]
            if not common:
                continue
            arm_m = _arm_metrics(common, arm, int(calibration_bins))
            ref_m = _arm_metrics(common, reference, int(calibration_bins))
            paired[f"{arm}_vs_{reference}"] = {
                "n": len(common),
                "brier_delta": arm_m["brier"] - ref_m["brier"],
                "log_loss_delta": arm_m["log_loss"] - ref_m["log_loss"],
                "ece_delta": arm_m["ece"] - ref_m["ece"],
                "better_brier": arm_m["brier"] < ref_m["brier"],
                "better_log_loss": arm_m["log_loss"] < ref_m["log_loss"],
            }

    by_month: dict[str, Any] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in data:
        grouped[_month(row["game_date"])].append(row)
    for month in sorted(grouped):
        month_rows = grouped[month]
        by_month[month] = {
            arm: _arm_metrics(month_rows, arm, int(calibration_bins))
            for arm in arm_list
        }

    return {
        "schema_version": "hr_research_ablation_evaluation_v1",
        "observation_count": len(data),
        "arms": list(arm_list),
        "overall": overall,
        "paired_deltas": paired,
        "chronological_months": by_month,
        "interpretation": {
            "negative_brier_delta_is_better": True,
            "negative_log_loss_delta_is_better": True,
            "negative_ece_delta_is_better": True,
            "random_shuffle_used": False,
        },
    }
