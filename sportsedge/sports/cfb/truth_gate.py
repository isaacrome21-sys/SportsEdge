"""Fail-closed CFB Truth Gate bound to the frozen CFB policy bytes.

This module evaluates evidence; it never creates Model_P, never converts market
prices into model probabilities, and never mutates deployment eligibility.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

CFB_TRUTH_GATE_ID = "CFB_TRUTH_GATE_V1"
CFB_TRUTH_GATE_POLICY_PATH = Path("config/cfb_truth_gate_v1.json")
CFB_TRUTH_GATE_POLICY_SHA256 = "9174bafd1e134cc30f3ac4afaf95692de15946617b9e69b545dfd264ab271702"


class CFBTruthGateError(ValueError):
    """Raised when policy or evidence cannot be evaluated safely."""


@dataclass(frozen=True)
class CFBTruthGateResult:
    gate_id: str
    policy_sha256: str
    market: str
    status: str
    passes: bool
    failures: tuple[str, ...]
    metrics: tuple[tuple[str, float | int], ...]
    diagnostics: tuple[tuple[str, float | int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "policy_sha256": self.policy_sha256,
            "market": self.market,
            "status": self.status,
            "passes": self.passes,
            "failures": list(self.failures),
            "metrics": dict(self.metrics),
            "diagnostics": dict(self.diagnostics),
            "governance": {
                "eligible_changed": False,
                "model_p_created": False,
                "market_prices_used_as_model_features": False,
                "candidate_edge_floor_is_separate": True,
            },
        }


class CFBTruthGate:
    """Evaluator for the immutable CFB_TRUTH_GATE_V1 judge."""

    EXPECTED_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL"})

    def __init__(self, policy_path: str | Path = CFB_TRUTH_GATE_POLICY_PATH):
        path = Path(policy_path)
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise CFBTruthGateError(f"CFB_TRUTH_GATE_POLICY_UNREADABLE:{path}") from exc
        digest = sha256(raw).hexdigest()
        if digest != CFB_TRUTH_GATE_POLICY_SHA256:
            raise CFBTruthGateError(
                f"CFB_TRUTH_GATE_POLICY_SHA256_MISMATCH:expected={CFB_TRUTH_GATE_POLICY_SHA256}:actual={digest}"
            )
        try:
            policy = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise CFBTruthGateError("CFB_TRUTH_GATE_POLICY_JSON_INVALID") from exc
        if not isinstance(policy, dict) or policy.get("policy_id") != CFB_TRUTH_GATE_ID:
            raise CFBTruthGateError("CFB_TRUTH_GATE_POLICY_ID_INVALID")
        markets = policy.get("markets")
        if not isinstance(markets, list) or frozenset(str(x).upper() for x in markets) != self.EXPECTED_MARKETS:
            raise CFBTruthGateError("CFB_TRUTH_GATE_MARKET_SURFACE_INVALID")
        gates = policy.get("hard_gates")
        if not isinstance(gates, dict):
            raise CFBTruthGateError("CFB_TRUTH_GATE_HARD_GATES_MISSING")
        self.policy = policy
        self.gates = gates
        self.policy_sha256 = digest

    @staticmethod
    def _bool(evidence: Mapping[str, Any], field: str) -> bool:
        value = evidence.get(field)
        if type(value) is not bool:
            raise CFBTruthGateError(f"CFB_TRUTH_GATE_BOOLEAN_REQUIRED:{field}")
        return value

    @staticmethod
    def _int(evidence: Mapping[str, Any], field: str) -> int:
        value = evidence.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CFBTruthGateError(f"CFB_TRUTH_GATE_NONNEGATIVE_INTEGER_REQUIRED:{field}")
        return value

    @staticmethod
    def _float(evidence: Mapping[str, Any], field: str) -> float:
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

    @staticmethod
    def _digest(evidence: Mapping[str, Any], field: str) -> str:
        value = evidence.get(field)
        if not isinstance(value, str) or len(value) != 64:
            raise CFBTruthGateError(f"CFB_TRUTH_GATE_SHA256_REQUIRED:{field}")
        try:
            int(value, 16)
        except ValueError as exc:
            raise CFBTruthGateError(f"CFB_TRUTH_GATE_SHA256_REQUIRED:{field}") from exc
        return value.lower()

    def evaluate(self, evidence: Mapping[str, Any]) -> CFBTruthGateResult:
        if not isinstance(evidence, Mapping):
            raise CFBTruthGateError("CFB_TRUTH_GATE_MAPPING_REQUIRED")
        market = str(evidence.get("market") or "").strip().upper()
        if market not in self.EXPECTED_MARKETS:
            raise CFBTruthGateError("CFB_TRUTH_GATE_MARKET_INVALID")
        if str(evidence.get("evidence_market") or "").strip().upper() != market:
            raise CFBTruthGateError("CFB_TRUTH_GATE_EVIDENCE_MARKET_MISMATCH")
        if evidence.get("evidence_policy_sha256") != self.policy_sha256:
            raise CFBTruthGateError("CFB_TRUTH_GATE_POLICY_SHA256_EVIDENCE_MISMATCH")

        pit = self._bool(evidence, "pit_reproducible")
        paired_prices = self._bool(evidence, "paired_historical_price_evidence_complete")
        recent_ok = self._bool(evidence, "recent_two_season_ok")
        model_bound = self._bool(evidence, "model_artifact_bound")
        source_bound = self._bool(evidence, "source_evidence_bound")
        settlement_complete = self._bool(evidence, "settlement_evidence_complete")
        self._digest(evidence, "model_artifact_sha256")
        self._digest(evidence, "source_manifest_sha256")
        self._digest(evidence, "validation_report_sha256")
        self._digest(evidence, "market_evidence_sha256")

        metrics: dict[str, float | int] = {
            "leakage_violations": self._int(evidence, "leakage_violations"),
            "n_forward_seasons": self._int(evidence, "n_forward_seasons"),
            "n_promoted": self._int(evidence, "n_promoted"),
            "brier_model": self._float(evidence, "brier_model"),
            "brier_market": self._float(evidence, "brier_market"),
            "logloss_model": self._float(evidence, "logloss_model"),
            "logloss_market": self._float(evidence, "logloss_market"),
            "season_fold_scoring_win_rate": self._float(evidence, "season_fold_scoring_win_rate"),
            "mean_novig_clv": self._float(evidence, "mean_novig_clv"),
            "clv_t_stat": self._float(evidence, "clv_t_stat"),
            "roi_after_vig": self._float(evidence, "roi_after_vig"),
            "calibration_slope": self._float(evidence, "calibration_slope"),
            "calibration_intercept": self._float(evidence, "calibration_intercept"),
            "ece": self._float(evidence, "ece"),
        }
        g = self.gates
        failures: list[str] = []
        if g["pit_reproducibility_required"] and not pit:
            failures.append("PIT_REPRODUCIBILITY_FAILED")
        if metrics["leakage_violations"] > g["max_leakage_violations"]:
            failures.append("LEAKAGE_VIOLATIONS_EXCEEDED")
        if metrics["n_forward_seasons"] < g["min_forward_seasons"]:
            failures.append("FORWARD_SEASONS_BELOW_FLOOR")
        if g["brier_must_beat_market"] and metrics["brier_model"] >= metrics["brier_market"]:
            failures.append("BRIER_DOES_NOT_BEAT_MARKET")
        if g["logloss_must_beat_market"] and metrics["logloss_model"] >= metrics["logloss_market"]:
            failures.append("LOGLOSS_DOES_NOT_BEAT_MARKET")
        fold_rate = float(metrics["season_fold_scoring_win_rate"])
        if not 0.0 <= fold_rate <= 1.0 or fold_rate < g["min_season_fold_scoring_win_rate"]:
            failures.append("SEASON_FOLD_SCORING_WIN_RATE_BELOW_FLOOR")
        if metrics["mean_novig_clv"] < g["min_mean_novig_clv"]:
            failures.append("MEAN_NOVIG_CLV_BELOW_FLOOR")
        if metrics["clv_t_stat"] < g["min_clv_t_stat"]:
            failures.append("CLV_T_STAT_BELOW_FLOOR")
        # Frozen judge requires positive after-vig ROI; 2% is a target diagnostic,
        # not the hard minimum. Preserve that distinction exactly.
        if metrics["roi_after_vig"] <= g["min_roi_after_vig"]:
            failures.append("ROI_AFTER_VIG_NOT_POSITIVE")
        if not g["calibration_slope_min"] <= metrics["calibration_slope"] <= g["calibration_slope_max"]:
            failures.append("CALIBRATION_SLOPE_OUT_OF_RANGE")
        if abs(float(metrics["calibration_intercept"])) > g["calibration_intercept_abs_max"]:
            failures.append("CALIBRATION_INTERCEPT_OUT_OF_RANGE")
        ece = float(metrics["ece"])
        if not 0.0 <= ece <= g["max_ece"]:
            failures.append("ECE_ABOVE_MAX")
        if metrics["n_promoted"] < g["min_promoted_sample_absolute"]:
            failures.append("PROMOTED_SAMPLE_BELOW_ABSOLUTE_FLOOR")
        if not recent_ok and not g["recent_two_season_deterioration_allowed"]:
            failures.append("RECENT_TWO_SEASON_DETERIORATION")
        if g["require_paired_historical_price_evidence"] and not paired_prices:
            failures.append("PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED")
        if not model_bound:
            failures.append("MODEL_ARTIFACT_UNBOUND")
        if not source_bound:
            failures.append("SOURCE_EVIDENCE_UNBOUND")
        if not settlement_complete:
            failures.append("SETTLEMENT_EVIDENCE_INCOMPLETE")

        diagnostics = {
            "target_forward_seasons": int(g["target_forward_seasons"]),
            "preferred_promoted_sample": int(g["preferred_promoted_sample"]),
            "target_roi_after_vig": float(g["target_roi_after_vig"]),
            "edge_floor": float(g["edge_floor"]),
        }
        return CFBTruthGateResult(
            gate_id=CFB_TRUTH_GATE_ID,
            policy_sha256=self.policy_sha256,
            market=market,
            status="PASS" if not failures else "BLOCKED",
            passes=not failures,
            failures=tuple(failures),
            metrics=tuple(sorted(metrics.items())),
            diagnostics=tuple(sorted(diagnostics.items())),
        )


def evaluate_cfb_truth_gate(evidence: Mapping[str, Any], *, policy_path: str | Path = CFB_TRUTH_GATE_POLICY_PATH) -> CFBTruthGateResult:
    return CFBTruthGate(policy_path).evaluate(evidence)


def cfb_candidate_meets_edge_floor(*, model_probability: float, no_vig_market_probability: float, live_two_sided_quote: bool = True, data_fresh: bool = True, exposure_limits_ok: bool = True) -> bool:
    """Apply the frozen 3% live edge gate after the historical market gate passes."""
    if type(live_two_sided_quote) is not bool or type(data_fresh) is not bool or type(exposure_limits_ok) is not bool:
        raise CFBTruthGateError("CFB_LIVE_GUARD_BOOLEAN_REQUIRED")
    if not (live_two_sided_quote and data_fresh and exposure_limits_ok):
        return False
    model_p = float(model_probability)
    market_p = float(no_vig_market_probability)
    if not (isfinite(model_p) and isfinite(market_p)):
        raise CFBTruthGateError("CFB_EDGE_FINITE_PROBABILITIES_REQUIRED")
    if not (0.0 <= model_p <= 1.0 and 0.0 <= market_p <= 1.0):
        raise CFBTruthGateError("CFB_EDGE_PROBABILITY_RANGE_INVALID")
    return model_p - market_p >= float(CFBTruthGate().gates["edge_floor"])
