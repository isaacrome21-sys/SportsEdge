"""CFB-specific promotion evidence gate.

This gate evaluates already-produced, artifact-bound evidence.  It never creates
Model_P, never derives evidence from market prices, and never mutates deployment
eligibility.  Missing or malformed evidence fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping

CFB_TRUTH_GATE_ID = "CFB_TRUTH_GATE_V1"
CFB_MIN_PROMOTED_ROWS = 200
CFB_MAX_ECE = 0.025
CFB_CALIBRATION_SLOPE_MIN = 0.90
CFB_CALIBRATION_SLOPE_MAX = 1.10
CFB_MAX_ABS_CALIBRATION_INTERCEPT = 0.03
CFB_MIN_CLV = 0.005
CFB_MIN_AFTER_VIG_ROI = 0.02
CFB_MIN_EDGE = 0.03


class CFBTruthGateError(ValueError):
    """Raised when evidence cannot be evaluated safely."""


@dataclass(frozen=True)
class CFBTruthGateResult:
    gate_id: str
    status: str
    passes: bool
    failures: tuple[str, ...]
    evidence_rows: int
    calibration_slope: float
    calibration_intercept: float
    ece: float
    mean_clv: float
    after_vig_roi: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "status": self.status,
            "passes": self.passes,
            "failures": list(self.failures),
            "evidence_rows": self.evidence_rows,
            "calibration_slope": self.calibration_slope,
            "calibration_intercept": self.calibration_intercept,
            "ece": self.ece,
            "mean_clv": self.mean_clv,
            "after_vig_roi": self.after_vig_roi,
            "thresholds": {
                "minimum_rows": CFB_MIN_PROMOTED_ROWS,
                "maximum_ece": CFB_MAX_ECE,
                "calibration_slope_min": CFB_CALIBRATION_SLOPE_MIN,
                "calibration_slope_max": CFB_CALIBRATION_SLOPE_MAX,
                "maximum_absolute_calibration_intercept": CFB_MAX_ABS_CALIBRATION_INTERCEPT,
                "minimum_clv": CFB_MIN_CLV,
                "minimum_after_vig_roi": CFB_MIN_AFTER_VIG_ROI,
                "minimum_live_edge": CFB_MIN_EDGE,
            },
            "governance": {
                "eligible_changed": False,
                "model_p_created": False,
                "market_prices_used_as_model_features": False,
                "candidate_edge_floor_is_separate": True,
            },
        }


def _required_bool(evidence: Mapping[str, Any], field: str) -> bool:
    value = evidence.get(field)
    if type(value) is not bool:
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_BOOLEAN_REQUIRED:{field}")
    return value


def _required_int(evidence: Mapping[str, Any], field: str) -> int:
    value = evidence.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_INTEGER_REQUIRED:{field}")
    if value < 0:
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_NONNEGATIVE_REQUIRED:{field}")
    return value


def _required_float(evidence: Mapping[str, Any], field: str) -> float:
    value = evidence.get(field)
    if isinstance(value, bool):
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_NUMBER_REQUIRED:{field}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_NUMBER_REQUIRED:{field}") from exc
    if not isfinite(number):
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_FINITE_REQUIRED:{field}")
    return number


def _required_digest(evidence: Mapping[str, Any], field: str) -> str:
    value = evidence.get(field)
    if not isinstance(value, str) or len(value) != 64:
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_SHA256_REQUIRED:{field}")
    try:
        int(value, 16)
    except ValueError as exc:
        raise CFBTruthGateError(f"CFB_TRUTH_GATE_SHA256_REQUIRED:{field}") from exc
    return value.lower()


def evaluate_cfb_truth_gate(evidence: Mapping[str, Any]) -> CFBTruthGateResult:
    """Evaluate frozen CFB evidence without creating or promoting evidence.

    Required booleans force the caller to prove PIT holdout discipline, exact
    model/evidence binding, and paired market settlement evidence.  The SHA fields
    make accidental use of detached summary metrics fail closed.
    """
    if not isinstance(evidence, Mapping):
        raise CFBTruthGateError("CFB_TRUTH_GATE_MAPPING_REQUIRED")

    pit_holdout_valid = _required_bool(evidence, "pit_holdout_valid")
    temporal_leakage_check_passed = _required_bool(evidence, "temporal_leakage_check_passed")
    model_artifact_bound = _required_bool(evidence, "model_artifact_bound")
    source_evidence_bound = _required_bool(evidence, "source_evidence_bound")
    paired_market_evidence_bound = _required_bool(evidence, "paired_market_evidence_bound")
    settlement_evidence_complete = _required_bool(evidence, "settlement_evidence_complete")

    _required_digest(evidence, "model_artifact_sha256")
    _required_digest(evidence, "source_manifest_sha256")
    _required_digest(evidence, "validation_report_sha256")
    _required_digest(evidence, "market_evidence_sha256")

    rows = _required_int(evidence, "evidence_rows")
    slope = _required_float(evidence, "calibration_slope")
    intercept = _required_float(evidence, "calibration_intercept")
    ece = _required_float(evidence, "ece")
    clv = _required_float(evidence, "mean_clv")
    roi = _required_float(evidence, "after_vig_roi")

    failures: list[str] = []
    if not pit_holdout_valid:
        failures.append("PIT_HOLDOUT_INVALID")
    if not temporal_leakage_check_passed:
        failures.append("TEMPORAL_LEAKAGE_CHECK_FAILED")
    if not model_artifact_bound:
        failures.append("MODEL_ARTIFACT_UNBOUND")
    if not source_evidence_bound:
        failures.append("SOURCE_EVIDENCE_UNBOUND")
    if not paired_market_evidence_bound:
        failures.append("PAIRED_MARKET_EVIDENCE_UNBOUND")
    if not settlement_evidence_complete:
        failures.append("SETTLEMENT_EVIDENCE_INCOMPLETE")
    if rows < CFB_MIN_PROMOTED_ROWS:
        failures.append("SAMPLE_DEPTH_BELOW_MINIMUM")
    if not (CFB_CALIBRATION_SLOPE_MIN <= slope <= CFB_CALIBRATION_SLOPE_MAX):
        failures.append("CALIBRATION_SLOPE_OUT_OF_RANGE")
    if abs(intercept) > CFB_MAX_ABS_CALIBRATION_INTERCEPT:
        failures.append("CALIBRATION_INTERCEPT_OUT_OF_RANGE")
    if ece > CFB_MAX_ECE or ece < 0.0:
        failures.append("ECE_OUT_OF_RANGE")
    if clv < CFB_MIN_CLV:
        failures.append("CLV_BELOW_MINIMUM")
    if roi < CFB_MIN_AFTER_VIG_ROI:
        failures.append("AFTER_VIG_ROI_BELOW_MINIMUM")

    return CFBTruthGateResult(
        gate_id=CFB_TRUTH_GATE_ID,
        status="PASS" if not failures else "BLOCKED",
        passes=not failures,
        failures=tuple(failures),
        evidence_rows=rows,
        calibration_slope=slope,
        calibration_intercept=intercept,
        ece=ece,
        mean_clv=clv,
        after_vig_roi=roi,
    )


def cfb_candidate_meets_edge_floor(*, model_probability: float, no_vig_market_probability: float) -> bool:
    """Apply the frozen live candidate edge floor after Model_P exists.

    This is deliberately separate from historical model promotion.  It cannot
    rescue a blocked model and must never be used to synthesize Model_P.
    """
    model_p = float(model_probability)
    market_p = float(no_vig_market_probability)
    if not (isfinite(model_p) and isfinite(market_p)):
        raise CFBTruthGateError("CFB_EDGE_FINITE_PROBABILITIES_REQUIRED")
    if not (0.0 <= model_p <= 1.0 and 0.0 <= market_p <= 1.0):
        raise CFBTruthGateError("CFB_EDGE_PROBABILITY_RANGE_INVALID")
    return model_p - market_p >= CFB_MIN_EDGE
