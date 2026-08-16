from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from math import log, sqrt
from typing import Any, Iterable, Mapping, Sequence

from .runtime import parse_timestamp
from .source_lineage import canonical_json_sha256

V7_SHADOW_SCHEMA_VERSION = "mlb_v7_shadow_v1"


class V7ShadowError(ValueError):
    pass


@dataclass(frozen=True)
class PromotionPolicy:
    min_calendar_days: int = 14
    min_unique_games: int = 200
    max_abs_calibration_z: float = 2.50
    max_brier_delta_vs_baseline: float = 0.0010
    max_logloss_delta_vs_baseline: float = 0.0020
    min_coverage: float = 0.90


@dataclass(frozen=True)
class ShadowMetrics:
    n: int
    brier: float
    log_loss: float
    calibration_z: float


def _utc(value: Any, field: str) -> datetime:
    try:
        dt = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise V7ShadowError(f"invalid {field}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise V7ShadowError(f"{field} must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _prob(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise V7ShadowError(f"{field} must be probability")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise V7ShadowError(f"{field} must be probability") from exc
    if not 0.0 < out < 1.0:
        raise V7ShadowError(f"{field} must be strictly between 0 and 1")
    return out


def normalize_shadow_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {"game_pk", "market", "prediction_as_of", "candidate_probability", "candidate_sha256", "feature_contract_sha256"}
    missing = sorted(required - set(row))
    if missing:
        raise V7ShadowError(f"missing shadow fields: {missing}")
    game_pk = int(row["game_pk"])
    market = str(row["market"]).strip().upper()
    if game_pk <= 0 or not market:
        raise V7ShadowError("invalid identity")
    as_of = _utc(row["prediction_as_of"], "prediction_as_of")
    out = {
        "schema_version": V7_SHADOW_SCHEMA_VERSION,
        "game_pk": game_pk,
        "market": market,
        "prediction_as_of": as_of.isoformat(),
        "candidate_probability": _prob(row["candidate_probability"], "candidate_probability"),
        "candidate_sha256": str(row["candidate_sha256"]),
        "feature_contract_sha256": str(row["feature_contract_sha256"]),
        "sportsbook_data_used": bool(row.get("sportsbook_data_used", False)),
    }
    if out["sportsbook_data_used"]:
        raise V7ShadowError("sportsbook data prohibited from candidate probability")
    if row.get("baseline_probability") is not None:
        out["baseline_probability"] = _prob(row["baseline_probability"], "baseline_probability")
    if row.get("outcome") is not None:
        outcome = int(row["outcome"])
        if outcome not in {0, 1}:
            raise V7ShadowError("outcome must be 0/1")
        out["outcome"] = outcome
        out["outcome_source"] = str(row.get("outcome_source") or "")
        if not out["outcome_source"]:
            raise V7ShadowError("outcome_source required when settled")
    out["row_sha256"] = canonical_json_sha256(out)
    return out


def merge_shadow_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[int, str], dict[str, Any]] = {}
    for raw in rows:
        row = normalize_shadow_row(raw)
        key = (row["game_pk"], row["market"])
        prior = merged.get(key)
        if prior is None:
            merged[key] = row
            continue
        if prior["candidate_sha256"] != row["candidate_sha256"] or prior["feature_contract_sha256"] != row["feature_contract_sha256"]:
            raise V7ShadowError("candidate/feature identity changed within one game-market")
        if prior["prediction_as_of"] != row["prediction_as_of"] or prior["candidate_probability"] != row["candidate_probability"]:
            raise V7ShadowError("immutable prediction conflict")
        if "outcome" in prior and "outcome" in row and prior["outcome"] != row["outcome"]:
            raise V7ShadowError("settlement conflict")
        if "outcome" not in prior and "outcome" in row:
            merged[key] = row
    return [merged[k] for k in sorted(merged)]


def score_probabilities(probabilities: Sequence[float], outcomes: Sequence[int]) -> ShadowMetrics:
    if len(probabilities) != len(outcomes) or not probabilities:
        raise V7ShadowError("paired non-empty probabilities/outcomes required")
    ps = [_prob(p, "probability") for p in probabilities]
    ys = [int(y) for y in outcomes]
    if any(y not in {0, 1} for y in ys):
        raise V7ShadowError("outcomes must be 0/1")
    n = len(ps)
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    eps = 1e-15
    ll = -sum(y * log(max(eps, p)) + (1-y) * log(max(eps, 1-p)) for p, y in zip(ps, ys)) / n
    expected = sum(ps)
    variance = sum(p * (1-p) for p in ps)
    z = 0.0 if variance <= 0 else (sum(ys) - expected) / sqrt(variance)
    return ShadowMetrics(n=n, brier=brier, log_loss=ll, calibration_z=z)


def evaluate_promotion(
    rows: Iterable[Mapping[str, Any]], *, policy: PromotionPolicy | None = None,
    eligible_slate_games: int | None = None, violation_count: int = 0,
) -> dict[str, Any]:
    policy = policy or PromotionPolicy()
    merged = merge_shadow_rows(rows)
    settled = [r for r in merged if "outcome" in r]
    reasons: list[str] = []
    if not settled:
        reasons.append("NO_SETTLED_EVIDENCE")
        metrics = None
        baseline = None
    else:
        metrics = score_probabilities([r["candidate_probability"] for r in settled], [r["outcome"] for r in settled])
        paired = [r for r in settled if "baseline_probability" in r]
        baseline = score_probabilities([r["baseline_probability"] for r in paired], [r["outcome"] for r in paired]) if paired else None
        if abs(metrics.calibration_z) > policy.max_abs_calibration_z:
            reasons.append("CALIBRATION_Z")
        if baseline is None or baseline.n != metrics.n:
            reasons.append("BASELINE_PAIRING_INCOMPLETE")
        else:
            if metrics.brier > baseline.brier + policy.max_brier_delta_vs_baseline:
                reasons.append("BRIER_DELTA")
            if metrics.log_loss > baseline.log_loss + policy.max_logloss_delta_vs_baseline:
                reasons.append("LOGLOSS_DELTA")

    unique_games = len({r["game_pk"] for r in settled})
    if unique_games < policy.min_unique_games:
        reasons.append("MIN_UNIQUE_GAMES")
    if settled:
        dates = sorted({_utc(r["prediction_as_of"], "prediction_as_of").date() for r in settled})
        calendar_span = (dates[-1] - dates[0]).days + 1
    else:
        calendar_span = 0
    if calendar_span < policy.min_calendar_days:
        reasons.append("MIN_CALENDAR_DAYS")
    coverage = 0.0 if not eligible_slate_games else unique_games / int(eligible_slate_games)
    if eligible_slate_games is None or coverage < policy.min_coverage:
        reasons.append("COVERAGE")
    if int(violation_count) != 0:
        reasons.append("VIOLATIONS")

    report = {
        "schema_version": V7_SHADOW_SCHEMA_VERSION,
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "unique_games": unique_games,
        "calendar_days": calendar_span,
        "coverage": coverage,
        "violation_count": int(violation_count),
        "policy": asdict(policy),
        "candidate_metrics": asdict(metrics) if metrics else None,
        "baseline_metrics": asdict(baseline) if baseline else None,
    }
    report["report_sha256"] = canonical_json_sha256(report)
    return report
