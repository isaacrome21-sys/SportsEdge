"""Normative historical evaluator for CFB_TRUTH_GATE_V1.

This supersedes older generic football promotion thresholds for CFB main markets.
It evaluates historical certification only; live quote/exposure gates are separate.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any


CFB_TRUTH_GATE_POLICY = "CFB_TRUTH_GATE_V1"
CFB_OFFICIAL_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL"})


class CFBTruthGateError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBTruthGateError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise CFBTruthGateError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class CFBTruthGateEvidence:
    market: str
    forward_seasons: int
    promoted_sample: int
    brier_model: float
    brier_novig_market: float
    logloss_model: float
    logloss_novig_market: float
    mean_novig_clv: float
    clv_tstat: float
    roi_after_vig: float
    calibration_slope: float
    calibration_intercept: float
    ece: float
    recent_2season_deterioration: bool
    leakage_violations: int
    paired_historical_prices_present: bool
    pit_reproducible: bool
    policy_sha_valid: bool
    benchmark_methodology_sha_valid: bool
    all_promoted_rows_replayable: bool

    def validate_types(self) -> "CFBTruthGateEvidence":
        if str(self.market).upper() not in CFB_OFFICIAL_MARKETS:
            raise CFBTruthGateError("MARKET_NOT_CFB_TRUTH_GATE_V1")
        for name in (
            "recent_2season_deterioration", "paired_historical_prices_present",
            "pit_reproducible", "policy_sha_valid", "benchmark_methodology_sha_valid",
            "all_promoted_rows_replayable",
        ):
            if type(getattr(self, name)) is not bool:
                raise CFBTruthGateError(f"{name}:BOOL_REQUIRED")
        for name in ("forward_seasons", "promoted_sample", "leakage_violations"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise CFBTruthGateError(f"{name}:NONNEGATIVE_INT_REQUIRED")
        for name in (
            "brier_model", "brier_novig_market", "logloss_model", "logloss_novig_market",
            "mean_novig_clv", "clv_tstat", "roi_after_vig", "calibration_slope",
            "calibration_intercept", "ece",
        ):
            _finite(getattr(self, name), name)
        return self


@dataclass(frozen=True)
class CFBTruthGateResult:
    policy: str
    market: str
    status: str
    failures: tuple[str, ...]
    evidence: CFBTruthGateEvidence

    @property
    def official(self) -> bool:
        return self.status == "OFFICIAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "market": self.market,
            "status": self.status,
            "failures": list(self.failures),
            "evidence": asdict(self.evidence),
        }


def evaluate_cfb_truth_gate_v1(evidence: CFBTruthGateEvidence) -> CFBTruthGateResult:
    e = evidence.validate_types()
    failures: list[str] = []
    if e.forward_seasons < 4:
        failures.append("FORWARD_SEASONS_LT_4")
    if e.promoted_sample < 200:
        failures.append("PROMOTED_SAMPLE_LT_200")
    if not e.brier_model < e.brier_novig_market:
        failures.append("BRIER_NOT_BETTER_THAN_NOVIG_MARKET")
    if not e.logloss_model < e.logloss_novig_market:
        failures.append("LOGLOSS_NOT_BETTER_THAN_NOVIG_MARKET")
    if e.mean_novig_clv < 0.005:
        failures.append("MEAN_NOVIG_CLV_LT_0_5PP")
    if e.clv_tstat < 2.0:
        failures.append("CLV_TSTAT_LT_2")
    if not e.roi_after_vig > 0.0:
        failures.append("ROI_AFTER_VIG_NOT_STRICTLY_POSITIVE")
    if not 0.90 <= e.calibration_slope <= 1.10:
        failures.append("CALIBRATION_SLOPE_OUT_OF_BOUNDS")
    if abs(e.calibration_intercept) > 0.03:
        failures.append("CALIBRATION_INTERCEPT_OUT_OF_BOUNDS")
    if e.ece > 0.025:
        failures.append("ECE_GT_0_025")
    if e.recent_2season_deterioration:
        failures.append("RECENT_2SEASON_DETERIORATION")
    if e.leakage_violations != 0:
        failures.append("LEAKAGE_VIOLATIONS_NONZERO")
    if not e.paired_historical_prices_present:
        failures.append("PAIRED_HISTORICAL_PRICES_MISSING")
    if not e.pit_reproducible:
        failures.append("PIT_NOT_REPRODUCIBLE")
    if not e.policy_sha_valid:
        failures.append("POLICY_SHA_INVALID")
    if not e.benchmark_methodology_sha_valid:
        failures.append("BENCHMARK_METHODOLOGY_SHA_INVALID")
    if not e.all_promoted_rows_replayable:
        failures.append("PROMOTED_ROWS_NOT_REPLAYABLE")
    return CFBTruthGateResult(
        policy=CFB_TRUTH_GATE_POLICY,
        market=str(e.market).upper(),
        status="OFFICIAL" if not failures else "FAILED",
        failures=tuple(failures),
        evidence=e,
    )
