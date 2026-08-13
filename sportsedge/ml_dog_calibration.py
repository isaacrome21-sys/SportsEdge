"""Predeclared MLB MONEYLINE favorite/underdog calibration evaluator.

Historical rows may diagnose a defect, but only genuinely forward rows generated
after the protocol commit can validate the underdog region and relax the interim
portfolio guard.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Iterable, Mapping

PROTOCOL_COMMIT_SHA = "34f3b9789a5189fa2d863a2ba7a41c06e6bc3f71"
PROTOCOL_COMMITTED_AT_UTC = datetime(2026, 8, 13, 17, 53, 28, tzinfo=timezone.utc)
MIN_FORWARD_DOG_N = 200
MIN_BUCKET_N = 100
MIN_HEAVY_DOG_N = 150

MODEL_BUCKETS = (
    (0.20, 0.30), (0.30, 0.40), (0.40, 0.50),
    (0.50, 0.60), (0.60, 0.70), (0.70, 0.80),
)


class MLCalibrationError(ValueError):
    pass


def _parse_utc(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MLCalibrationError("GENERATED_AT_MISSING")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLCalibrationError("GENERATED_AT_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MLCalibrationError("GENERATED_AT_NOT_AWARE")
    return dt.astimezone(timezone.utc)


def _finite_prob(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError) as exc:
        raise MLCalibrationError("MODEL_P_INVALID") from exc
    if not math.isfinite(p) or not 0.0 < p < 1.0:
        raise MLCalibrationError("MODEL_P_INVALID")
    return p


def _american(value: Any) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise MLCalibrationError("AMERICAN_ODDS_INVALID") from exc
    if not math.isfinite(x) or (-100 < x < 100):
        raise MLCalibrationError("AMERICAN_ODDS_INVALID")
    return x


def _classify_price(odds: float) -> str:
    if odds < -100:
        return "FAVORITE"
    if odds > 100:
        return "UNDERDOG"
    return "PICKEM"


def _dog_band(odds: float) -> str | None:
    if odds <= 100:
        return None
    if odds <= 124:
        return "DOG_100_124"
    if odds <= 149:
        return "DOG_125_149"
    if odds <= 174:
        return "DOG_150_174"
    return "DOG_175_PLUS"


def _model_bucket(p: float) -> str:
    for lo, hi in MODEL_BUCKETS:
        if lo <= p < hi:
            return f"P_{lo:.2f}_{hi:.2f}"
    return "P_LOW_TAIL" if p < MODEL_BUCKETS[0][0] else "P_HIGH_TAIL"


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"n": 0}
    ps = [r["model_p"] for r in rows]
    ys = [1.0 if r["outcome_win"] else 0.0 for r in rows]
    pred = sum(ps) / n
    actual = sum(ys) / n
    bias = pred - actual
    var = sum(p * (1.0 - p) for p in ps) / n
    se = math.sqrt(var / n) if var > 0 else 0.0
    z = abs(bias) / se if se > 0 else (0.0 if bias == 0 else math.inf)
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    eps = 1e-12
    log_loss = -sum(y * math.log(max(eps, p)) + (1.0-y) * math.log(max(eps, 1.0-p)) for p, y in zip(ps, ys)) / n
    base = min(1.0 - eps, max(eps, actual))
    base_brier = sum((base-y) ** 2 for y in ys) / n
    base_log_loss = -sum(y * math.log(base) + (1.0-y) * math.log(1.0-base) for y in ys) / n
    return {
        "n": n,
        "mean_model_p": pred,
        "realized_win_rate": actual,
        "calibration_bias": bias,
        "abs_calibration_bias": abs(bias),
        "calibration_z": z,
        "brier": brier,
        "log_loss": log_loss,
        "constant_base_rate_brier": base_brier,
        "constant_base_rate_log_loss": base_log_loss,
        "brier_skill_vs_constant": 1.0 - brier / base_brier if base_brier > 0 else None,
    }


def _dedupe_latest(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping) or str(raw.get("market") or "").upper() != "MONEYLINE":
            continue
        game_id = str(raw.get("game_id") or "").strip()
        side = str(raw.get("side") or "").upper().strip()
        if not game_id or side not in {"HOME", "AWAY"}:
            continue
        generated = _parse_utc(raw.get("generated_at_utc"))
        first_pitch = _parse_utc(raw.get("first_pitch_utc"))
        if generated >= first_pitch:
            continue
        row = dict(raw)
        row["generated_dt"] = generated
        row["model_p"] = _finite_prob(raw.get("model_p"))
        row["american_odds"] = _american(raw.get("american_odds"))
        if type(raw.get("outcome_win")) is not bool:
            continue
        key = (game_id, side)
        prior = latest.get(key)
        if prior is None or generated > prior["generated_dt"]:
            latest[key] = row
    return list(latest.values())


def _monotonicity(bucket_metrics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ordered = []
    for lo, hi in MODEL_BUCKETS:
        name = f"P_{lo:.2f}_{hi:.2f}"
        m = bucket_metrics.get(name) or {}
        if int(m.get("n") or 0) >= MIN_BUCKET_N:
            ordered.append((name, float(m["realized_win_rate"])))
    inversions = []
    for (a_name, a), (b_name, b) in zip(ordered, ordered[1:]):
        if b < a:
            inversions.append({"from": a_name, "to": b_name, "magnitude": a-b})
    passes = len(inversions) == 0 or (len(inversions) == 1 and inversions[0]["magnitude"] <= 0.020)
    return {"qualifying_buckets": ordered, "inversions": inversions, "passes": passes}


def evaluate_ml_favorite_dog_calibration(
    settlement_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = _dedupe_latest(settlement_rows)
    for row in rows:
        row["price_class"] = _classify_price(row["american_odds"])
        row["dog_band"] = _dog_band(row["american_odds"])
        row["model_bucket"] = _model_bucket(row["model_p"])
        row["is_forward"] = row["generated_dt"] > PROTOCOL_COMMITTED_AT_UTC

    def report(subset: list[dict[str, Any]]) -> dict[str, Any]:
        overall = _metrics(subset)
        by_bucket = {name: _metrics([r for r in subset if r["model_bucket"] == name]) for name in sorted({r["model_bucket"] for r in subset})}
        return {"overall": overall, "by_model_bucket": by_bucket, "monotonicity": _monotonicity(by_bucket)}

    favorite = [r for r in rows if r["price_class"] == "FAVORITE"]
    dog = [r for r in rows if r["price_class"] == "UNDERDOG"]
    forward_dog = [r for r in dog if r["is_forward"]]
    dog_bands = {name: _metrics([r for r in forward_dog if r["dog_band"] == name]) for name in ("DOG_100_124","DOG_125_149","DOG_150_174","DOG_175_PLUS")}
    f_report = report(favorite)
    d_report = report(dog)
    fd_report = report(forward_dog)

    overall = fd_report["overall"]
    reasons: list[str] = []
    if int(overall.get("n") or 0) < MIN_FORWARD_DOG_N:
        reasons.append("FORWARD_DOG_SAMPLE_LT_200")
    if overall.get("n"):
        if float(overall["abs_calibration_bias"]) > 0.020:
            reasons.append("DOG_OVERALL_BIAS_GT_0.020")
        if float(overall["calibration_z"]) > 2.50:
            reasons.append("DOG_OVERALL_Z_GT_2.50")
        if float(overall["brier"]) > float(overall["constant_base_rate_brier"]):
            reasons.append("DOG_BRIER_WORSE_THAN_CONSTANT")
        if float(overall["log_loss"]) > float(overall["constant_base_rate_log_loss"]):
            reasons.append("DOG_LOGLOSS_WORSE_THAN_CONSTANT")
    for name, m in fd_report["by_model_bucket"].items():
        if int(m.get("n") or 0) >= MIN_BUCKET_N:
            if float(m["abs_calibration_bias"]) > 0.030:
                reasons.append(f"{name}_BIAS_GT_0.030")
            if float(m["calibration_z"]) > 2.50:
                reasons.append(f"{name}_Z_GT_2.50")
    for name, m in dog_bands.items():
        if int(m.get("n") or 0) >= MIN_BUCKET_N:
            if float(m["abs_calibration_bias"]) > 0.030:
                reasons.append(f"{name}_BIAS_GT_0.030")
            if float(m["calibration_z"]) > 2.50:
                reasons.append(f"{name}_Z_GT_2.50")
    if not fd_report["monotonicity"]["passes"]:
        reasons.append("DOG_MODEL_BUCKET_MONOTONICITY_FAIL")

    heavy = dog_bands["DOG_175_PLUS"]
    heavy_validated = bool(
        int(heavy.get("n") or 0) >= MIN_HEAVY_DOG_N
        and float(heavy.get("abs_calibration_bias") or math.inf) <= 0.030
        and float(heavy.get("calibration_z") or math.inf) <= 2.50
    )

    return {
        "schema_version": "sportsedge_ml_dog_calibration_v1",
        "protocol_commit_sha": PROTOCOL_COMMIT_SHA,
        "protocol_committed_at_utc": PROTOCOL_COMMITTED_AT_UTC.isoformat(),
        "deduped_moneyline_rows": len(rows),
        "favorite_diagnostic": f_report,
        "underdog_diagnostic_all_available": d_report,
        "underdog_forward_validation": fd_report,
        "forward_dog_price_bands": dog_bands,
        "dog_calibration_validated": len(reasons) == 0,
        "dog_calibration_reasons": reasons,
        "dog_175_plus_validated": heavy_validated,
    }
