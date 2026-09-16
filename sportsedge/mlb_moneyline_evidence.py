"""Fail-closed evidence metrics for the MLB MONEYLINE Model_P lane."""
from __future__ import annotations

from datetime import datetime, timezone
from math import exp, isfinite, log
from statistics import fmean
from typing import Any, Iterable, Mapping

EVIDENCE_VERSION = "mlb_moneyline_evidence_v1"


class MLBMoneylineEvidenceError(ValueError):
    pass


def _prob(value: Any) -> float:
    try:
        p = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineEvidenceError("model_p must be numeric") from exc
    if not isfinite(p) or not 0 < p < 1:
        raise MLBMoneylineEvidenceError("model_p must be strictly between 0 and 1")
    return p


def _outcome(value: Any) -> int:
    try:
        y = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBMoneylineEvidenceError("outcome must be 0 or 1") from exc
    if y not in (0, 1):
        raise MLBMoneylineEvidenceError("outcome must be 0 or 1")
    return y


def _logistic(x: float) -> float:
    if x >= 0:
        z = exp(-x)
        return 1 / (1 + z)
    z = exp(x)
    return z / (1 + z)


def _fit(ps: list[float], ys: list[int]) -> tuple[float, float]:
    xs = [log(p / (1 - p)) for p in ps]
    a, b = 0.0, 1.0
    for _ in range(100):
        g0 = g1 = h00 = h01 = h11 = 0.0
        for x, y in zip(xs, ys):
            mu = _logistic(a + b * x)
            w = max(mu * (1 - mu), 1e-12)
            r = y - mu
            g0 += r
            g1 += r * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-12:
            raise MLBMoneylineEvidenceError("calibration fit is singular")
        da = (g0 * h11 - g1 * h01) / det
        db = (g1 * h00 - g0 * h01) / det
        a += da
        b += db
        if max(abs(da), abs(db)) < 1e-10:
            return a, b
        if not isfinite(a) or not isfinite(b) or max(abs(a), abs(b)) > 1e6:
            raise MLBMoneylineEvidenceError("calibration fit did not converge")
    raise MLBMoneylineEvidenceError("calibration fit did not converge")


def _ece(ps: list[float], ys: list[int], bins: int) -> float:
    if bins < 2:
        raise MLBMoneylineEvidenceError("ece_bins must be >= 2")
    n = len(ps)
    total = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        members = [
            (p, y)
            for p, y in zip(ps, ys)
            if lo <= p < hi or (i == bins - 1 and p == 1.0)
        ]
        if members:
            total += len(members) / n * abs(
                fmean(p for p, _ in members) - fmean(y for _, y in members)
            )
    return total


def evaluate_moneyline_predictions(
    rows: Iterable[Mapping[str, Any]], *, min_sample: int = 200, ece_bins: int = 10
) -> dict[str, Any]:
    data = list(rows)
    ps: list[float] = []
    ys: list[int] = []
    if min_sample < 1:
        raise MLBMoneylineEvidenceError("min_sample must be positive")
    for i, row in enumerate(data):
        if row.get("market_blind") is not True:
            raise MLBMoneylineEvidenceError(f"row {i}: market_blind must be true")

        def parse(value: Any) -> datetime:
            try:
                dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            except ValueError as exc:
                raise MLBMoneylineEvidenceError(f"row {i}: PIT timestamps required") from exc
            if dt.tzinfo is None:
                raise MLBMoneylineEvidenceError(f"row {i}: timezone required")
            return dt.astimezone(timezone.utc)

        if parse(row.get("feature_asof_ts")) >= parse(row.get("event_start_ts")):
            raise MLBMoneylineEvidenceError(f"row {i}: PIT_LEAKAGE")
        ps.append(_prob(row.get("model_p")))
        ys.append(_outcome(row.get("outcome")))

    n = len(ps)
    thresholds = {
        "min_sample": min_sample,
        "slope": [0.90, 1.10],
        "abs_intercept_max": 0.03,
        "ece_max": 0.025,
    }
    if not n:
        return {
            "evidence_version": EVIDENCE_VERSION,
            "n": 0,
            "thresholds": thresholds,
            "sample_gate_pass": False,
            "calibration_gate_pass": False,
            "status": "BLOCKED_NO_PREDICTIONS",
            "promotion_authority": False,
            "clv_status": "SEPARATE_EVIDENCE_REQUIRED",
        }

    eps = 1e-15
    brier = fmean((p - y) ** 2 for p, y in zip(ps, ys))
    ll = -fmean(
        y * log(max(p, eps)) + (1 - y) * log(max(1 - p, eps))
        for p, y in zip(ps, ys)
    )
    ece = _ece(ps, ys, ece_bins)
    if n < min_sample:
        return {
            "evidence_version": EVIDENCE_VERSION,
            "n": n,
            "brier": brier,
            "log_loss": ll,
            "calibration_slope": None,
            "calibration_intercept": None,
            "ece": ece,
            "ece_bins": ece_bins,
            "thresholds": thresholds,
            "sample_gate_pass": False,
            "calibration_gate_pass": False,
            "status": "BLOCKED_CALIBRATION_OR_SAMPLE",
            "clv_status": "SEPARATE_EVIDENCE_REQUIRED",
            "promotion_authority": False,
        }

    intercept, slope = _fit(ps, ys)
    calibration_pass = (
        0.90 <= slope <= 1.10 and abs(intercept) <= 0.03 and ece <= 0.025
    )
    return {
        "evidence_version": EVIDENCE_VERSION,
        "n": n,
        "brier": brier,
        "log_loss": ll,
        "calibration_slope": slope,
        "calibration_intercept": intercept,
        "ece": ece,
        "ece_bins": ece_bins,
        "thresholds": thresholds,
        "sample_gate_pass": True,
        "calibration_gate_pass": calibration_pass,
        "status": (
            "CALIBRATION_PASS_CLV_PENDING"
            if calibration_pass
            else "BLOCKED_CALIBRATION_OR_SAMPLE"
        ),
        "clv_status": "SEPARATE_EVIDENCE_REQUIRED",
        "promotion_authority": False,
    }
