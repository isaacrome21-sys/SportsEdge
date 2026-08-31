"""Normative historical evaluator for MLB_TRUTH_GATE_V1.

Certification is per canonical market ID. ``market_family`` is grouping metadata only;
a pooled family result may not certify sibling markets. Live quote/exposure checks are
separate from this historical certification state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any


MLB_TRUTH_GATE_POLICY = "MLB_TRUTH_GATE_V1"
MLB_MARKET_FAMILIES = frozenset({"V7_GAME", "HITTER_JOINT", "PITCHER_JOINT", "F5", "SPECIALIZED"})


class MLBTruthGateError(ValueError):
    pass


def _finite(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise MLBTruthGateError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise MLBTruthGateError(f"{field}:FINITE_REQUIRED")
    return out


@dataclass(frozen=True)
class MLBTruthGateEvidence:
    market_id: str
    market_family: str
    forward_seasons: int
    promoted_sample: int
    season_fold_scoring_win_rate: float
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
    pit_reproducible: bool
    policy_sha_valid: bool
    benchmark_methodology_sha_valid: bool
    model_code_sha_valid: bool
    feature_schema_sha_valid: bool
    structural_change_clearance: bool
    coherent_joint_constraints: bool
    all_promoted_rows_replayable: bool

    def validate_types(self) -> "MLBTruthGateEvidence":
        if not str(self.market_id).strip():
            raise MLBTruthGateError("CANONICAL_MARKET_ID_REQUIRED")
        if str(self.market_family).upper() not in MLB_MARKET_FAMILIES:
            raise MLBTruthGateError("MARKET_FAMILY_NOT_MLB_TRUTH_GATE_V1")
        for name in (
            "recent_2season_deterioration", "pit_reproducible", "policy_sha_valid",
            "benchmark_methodology_sha_valid", "model_code_sha_valid", "feature_schema_sha_valid",
            "structural_change_clearance", "coherent_joint_constraints", "all_promoted_rows_replayable",
        ):
            if type(getattr(self, name)) is not bool:
                raise MLBTruthGateError(f"{name}:BOOL_REQUIRED")
        for name in ("forward_seasons", "promoted_sample", "leakage_violations"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MLBTruthGateError(f"{name}:NONNEGATIVE_INT_REQUIRED")
        for name in (
            "season_fold_scoring_win_rate", "brier_model", "brier_novig_market",
            "logloss_model", "logloss_novig_market", "mean_novig_clv", "clv_tstat",
            "roi_after_vig", "calibration_slope", "calibration_intercept", "ece",
        ):
            _finite(getattr(self, name), name)
        if not 0.0 <= self.season_fold_scoring_win_rate <= 1.0:
            raise MLBTruthGateError("SEASON_FOLD_SCORING_WIN_RATE_RANGE")
        if self.ece < 0.0:
            raise MLBTruthGateError("ECE_NEGATIVE")
        return self


@dataclass(frozen=True)
class MLBTruthGateResult:
    policy: str
    market_id: str
    market_family: str
    status: str
    failures: tuple[str, ...]
    evidence: MLBTruthGateEvidence

    @property
    def official(self) -> bool:
        return self.status == "OFFICIAL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "market_id": self.market_id,
            "market_family": self.market_family,
            "status": self.status,
            "failures": list(self.failures),
            "evidence": asdict(self.evidence),
        }


def evaluate_mlb_truth_gate_v1(evidence: MLBTruthGateEvidence) -> MLBTruthGateResult:
    e = evidence.validate_types()
    failures: list[str] = []
    if e.forward_seasons < 3:
        failures.append("FORWARD_SEASONS_LT_3")
    if e.promoted_sample < 200:
        failures.append("PROMOTED_SAMPLE_LT_200")
    if e.season_fold_scoring_win_rate < 0.60:
        failures.append("SEASON_FOLD_SCORING_WIN_RATE_LT_0_60")
    if not e.brier_model < e.brier_novig_market:
        failures.append("BRIER_NOT_BETTER_THAN_NOVIG_MARKET")
    if not e.logloss_model < e.logloss_novig_market:
        failures.append("LOGLOSS_NOT_BETTER_THAN_NOVIG_MARKET")
    if e.mean_novig_clv < 0.004:
        failures.append("MEAN_NOVIG_CLV_LT_0_4PP")
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
    if not e.pit_reproducible:
        failures.append("PIT_NOT_REPRODUCIBLE")
    if not e.policy_sha_valid:
        failures.append("POLICY_SHA_INVALID")
    if not e.benchmark_methodology_sha_valid:
        failures.append("BENCHMARK_METHODOLOGY_SHA_INVALID")
    if not e.model_code_sha_valid:
        failures.append("MODEL_CODE_SHA_INVALID")
    if not e.feature_schema_sha_valid:
        failures.append("FEATURE_SCHEMA_SHA_INVALID")
    if not e.structural_change_clearance:
        failures.append("STRUCTURAL_CHANGE_CLEARANCE_MISSING")
    if not e.coherent_joint_constraints:
        failures.append("COHERENT_JOINT_CONSTRAINTS_FAILED")
    if not e.all_promoted_rows_replayable:
        failures.append("PROMOTED_ROWS_NOT_REPLAYABLE")
    return MLBTruthGateResult(
        policy=MLB_TRUTH_GATE_POLICY,
        market_id=str(e.market_id).strip().upper(),
        market_family=str(e.market_family).upper(),
        status="OFFICIAL" if not failures else "FAILED",
        failures=tuple(failures),
        evidence=e,
    )
