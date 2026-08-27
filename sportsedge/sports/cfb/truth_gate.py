"""
SportsEdge CFB Truth Gate.

Policy numbers live in config/cfb_truth_gate_v1.json.
This module owns semantics only. Fail-closed. No overrides.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from math import isfinite
from pathlib import Path
from typing import Any, Mapping


class TruthGateError(ValueError):
    pass


class PromotionState(str, Enum):
    NO_ENGINE = "NO_ENGINE"
    EXPERIMENTAL = "EXPERIMENTAL"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    VALIDATED_MODEL = "VALIDATED_MODEL"
    READY_FOR_POLICY = "READY_FOR_POLICY"
    OFFICIAL = "OFFICIAL"
    REVOKED = "REVOKED"


class CandidateBetStatus(str, Enum):
    BLOCKED = "BLOCKED"
    NO_BET = "NO_BET"
    OFFICIAL_BET = "OFFICIAL_BET"


@dataclass(frozen=True)
class GateReport:
    market: str
    status: str
    policy_id: str
    policy_version: str
    policy_sha256: str
    hard_gate_pass: bool
    failures: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    promoted: bool = False
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateDecision:
    market: str
    bet_status: str
    policy_id: str
    policy_sha256: str
    edge: float | None
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise TruthGateError(f"{name}:NUMERIC_REQUIRED")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise TruthGateError(f"{name}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise TruthGateError(f"{name}:FINITE_REQUIRED")
    return out


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise TruthGateError(f"{name}:INTEGER_REQUIRED")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise TruthGateError(f"{name}:INTEGER_REQUIRED") from exc
    return out


class TruthGate:
    def __init__(self, policy_path: str | Path = "config/cfb_truth_gate_v1.json"):
        self.policy_path = Path(policy_path)
        self.policy = self._load_policy()
        self.policy_sha256 = hashlib.sha256(self.policy_path.read_bytes()).hexdigest()
        self.gates = dict(self.policy["hard_gates"])
        self.diagnostics_cfg = dict(self.policy.get("diagnostics_only", {}))
        self.markets = frozenset(str(x).strip().upper() for x in self.policy["markets"])
        self._validate_policy()

    def _load_policy(self) -> dict[str, Any]:
        try:
            raw = self.policy_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TruthGateError("CFB_TRUTH_GATE_POLICY_UNREADABLE") from exc
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TruthGateError("CFB_TRUTH_GATE_POLICY_JSON_INVALID") from exc
        if not isinstance(payload, dict):
            raise TruthGateError("CFB_TRUTH_GATE_POLICY_OBJECT_REQUIRED")
        return payload

    def _validate_policy(self) -> None:
        if str(self.policy.get("policy_id") or "") != "CFB_TRUTH_GATE_V1":
            raise TruthGateError("CFB_TRUTH_GATE_POLICY_ID_INVALID")
        if not str(self.policy.get("version") or "").strip():
            raise TruthGateError("CFB_TRUTH_GATE_POLICY_VERSION_REQUIRED")
        if self.markets != frozenset({"MONEYLINE", "SPREAD", "TOTAL"}):
            raise TruthGateError("CFB_TRUTH_GATE_MARKET_SURFACE_INVALID")
        required = {
            "pit_reproducibility_required",
            "max_leakage_violations",
            "min_forward_seasons",
            "target_forward_seasons",
            "brier_must_beat_market",
            "logloss_must_beat_market",
            "min_season_fold_scoring_win_rate",
            "min_mean_novig_clv",
            "min_clv_t_stat",
            "min_roi_after_vig",
            "target_roi_after_vig",
            "calibration_slope_min",
            "calibration_slope_max",
            "calibration_intercept_abs_max",
            "max_ece",
            "min_promoted_sample_absolute",
            "preferred_promoted_sample",
            "recent_two_season_deterioration_allowed",
            "require_paired_historical_price_evidence",
            "require_live_two_sided_quote",
            "require_data_freshness",
            "require_frozen_policy_hash",
            "edge_floor",
            "require_exposure_limits",
        }
        missing = sorted(required - set(self.gates))
        if missing:
            raise TruthGateError("CFB_TRUTH_GATE_POLICY_FIELDS_MISSING:" + ",".join(missing))
        if self.gates["min_forward_seasons"] > self.gates["target_forward_seasons"]:
            raise TruthGateError("CFB_TRUTH_GATE_FORWARD_SEASON_TARGET_INVALID")
        if self.gates["min_promoted_sample_absolute"] > self.gates["preferred_promoted_sample"]:
            raise TruthGateError("CFB_TRUTH_GATE_SAMPLE_TARGET_INVALID")
        if not 0.0 <= float(self.gates["edge_floor"]) <= 1.0:
            raise TruthGateError("CFB_TRUTH_GATE_EDGE_FLOOR_INVALID")

    def _market(self, market: str) -> str:
        canonical = str(market or "").strip().upper()
        if canonical not in self.markets:
            raise TruthGateError(f"CFB_TRUTH_GATE_MARKET_UNSUPPORTED:{canonical or 'MISSING'}")
        return canonical

    def evaluate(
        self,
        market: str,
        *,
        pit_reproducible: bool,
        leakage_violations: int,
        n_forward_seasons: int,
        brier_model: float,
        brier_market: float,
        logloss_model: float,
        logloss_market: float,
        season_fold_scoring_win_rate: float,
        mean_novig_clv: float,
        clv_t_stat: float,
        roi_after_vig: float,
        calibration_slope: float,
        calibration_intercept: float,
        ece: float,
        n_promoted: int,
        recent_two_season_ok: bool,
        paired_historical_price_evidence_complete: bool,
        evidence_policy_sha256: str,
        hit_rates: Mapping[str, float] | None = None,
    ) -> GateReport:
        """Evaluate one market's frozen historical evidence. Any hard failure blocks promotion."""
        canonical = self._market(market)
        g = self.gates
        failures: list[str] = []

        leak_n = _integer(leakage_violations, "leakage_violations")
        forward_n = _integer(n_forward_seasons, "n_forward_seasons")
        promoted_n = _integer(n_promoted, "n_promoted")
        if leak_n < 0 or forward_n < 0 or promoted_n < 0:
            raise TruthGateError("CFB_TRUTH_GATE_NEGATIVE_COUNT")

        brier_m = _finite(brier_model, "brier_model")
        brier_k = _finite(brier_market, "brier_market")
        log_m = _finite(logloss_model, "logloss_model")
        log_k = _finite(logloss_market, "logloss_market")
        fold_rate = _finite(season_fold_scoring_win_rate, "season_fold_scoring_win_rate")
        clv = _finite(mean_novig_clv, "mean_novig_clv")
        clv_t = _finite(clv_t_stat, "clv_t_stat")
        roi = _finite(roi_after_vig, "roi_after_vig")
        slope = _finite(calibration_slope, "calibration_slope")
        intercept = _finite(calibration_intercept, "calibration_intercept")
        ece_value = _finite(ece, "ece")

        if not 0.0 <= fold_rate <= 1.0:
            raise TruthGateError("season_fold_scoring_win_rate:PROBABILITY_REQUIRED")
        if not 0.0 <= ece_value <= 1.0:
            raise TruthGateError("ece:PROBABILITY_REQUIRED")
        if type(pit_reproducible) is not bool:
            raise TruthGateError("pit_reproducible:BOOL_REQUIRED")
        if type(recent_two_season_ok) is not bool:
            raise TruthGateError("recent_two_season_ok:BOOL_REQUIRED")
        if type(paired_historical_price_evidence_complete) is not bool:
            raise TruthGateError("paired_historical_price_evidence_complete:BOOL_REQUIRED")

        if g["pit_reproducibility_required"] and not pit_reproducible:
            failures.append("PIT_REPRODUCIBILITY_FAILED")
        if leak_n > int(g["max_leakage_violations"]):
            failures.append("LEAKAGE_VIOLATIONS_EXCEEDED")
        if forward_n < int(g["min_forward_seasons"]):
            failures.append("FORWARD_SEASONS_BELOW_FLOOR")
        if g["brier_must_beat_market"] and brier_m >= brier_k:
            failures.append("BRIER_DOES_NOT_BEAT_MARKET")
        if g["logloss_must_beat_market"] and log_m >= log_k:
            failures.append("LOGLOSS_DOES_NOT_BEAT_MARKET")
        if fold_rate < float(g["min_season_fold_scoring_win_rate"]):
            failures.append("SEASON_FOLD_SCORING_WIN_RATE_BELOW_FLOOR")
        if clv < float(g["min_mean_novig_clv"]):
            failures.append("MEAN_NOVIG_CLV_BELOW_FLOOR")
        if clv_t < float(g["min_clv_t_stat"]):
            failures.append("CLV_T_STAT_BELOW_FLOOR")
        if roi <= float(g["min_roi_after_vig"]):
            failures.append("ROI_AFTER_VIG_NOT_POSITIVE")
        if not float(g["calibration_slope_min"]) <= slope <= float(g["calibration_slope_max"]):
            failures.append("CALIBRATION_SLOPE_OUT_OF_RANGE")
        if abs(intercept) > float(g["calibration_intercept_abs_max"]):
            failures.append("CALIBRATION_INTERCEPT_OUT_OF_RANGE")
        if ece_value > float(g["max_ece"]):
            failures.append("ECE_ABOVE_MAX")
        if promoted_n < int(g["min_promoted_sample_absolute"]):
            failures.append("PROMOTED_SAMPLE_BELOW_ABSOLUTE_FLOOR")
        if not recent_two_season_ok and not g["recent_two_season_deterioration_allowed"]:
            failures.append("RECENT_TWO_SEASON_DETERIORATION")
        if g["require_paired_historical_price_evidence"] and not paired_historical_price_evidence_complete:
            failures.append("PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED")

        supplied_policy_sha = str(evidence_policy_sha256 or "").strip().lower()
        if g["require_frozen_policy_hash"]:
            if len(supplied_policy_sha) != 64:
                failures.append("FROZEN_POLICY_HASH_MISSING")
            elif supplied_policy_sha != self.policy_sha256:
                failures.append("FROZEN_POLICY_HASH_MISMATCH")

        hard_pass = not failures
        incomplete_reasons = {
            "FORWARD_SEASONS_BELOW_FLOOR",
            "PROMOTED_SAMPLE_BELOW_ABSOLUTE_FLOOR",
            "PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED",
            "FROZEN_POLICY_HASH_MISSING",
        }
        if hard_pass:
            status = PromotionState.OFFICIAL
        elif any(reason in incomplete_reasons for reason in failures):
            status = PromotionState.EVIDENCE_INCOMPLETE
        else:
            status = PromotionState.EXPERIMENTAL

        diagnostics: dict[str, Any] = {
            "target_forward_seasons": int(g["target_forward_seasons"]),
            "preferred_promoted_sample": int(g["preferred_promoted_sample"]),
            "target_roi_after_vig": float(g["target_roi_after_vig"]),
        }
        if hit_rates is not None:
            diagnostics["hit_rates"] = {str(k): _finite(v, f"hit_rates.{k}") for k, v in hit_rates.items()}
            diagnostics["hit_rate_targets"] = dict(self.diagnostics_cfg.get("hit_rate_buckets", {}))

        metrics = {
            "mean_novig_clv": clv,
            "clv_t_stat": clv_t,
            "roi_after_vig": roi,
            "brier_model": brier_m,
            "brier_market": brier_k,
            "logloss_model": log_m,
            "logloss_market": log_k,
            "calibration_slope": slope,
            "calibration_intercept": intercept,
            "ece": ece_value,
            "n_promoted": promoted_n,
            "n_forward_seasons": forward_n,
            "season_fold_scoring_win_rate": fold_rate,
            "leakage_violations": leak_n,
            "paired_historical_price_evidence_complete": paired_historical_price_evidence_complete,
        }

        return GateReport(
            market=canonical,
            status=status.value,
            policy_id=str(self.policy["policy_id"]),
            policy_version=str(self.policy["version"]),
            policy_sha256=self.policy_sha256,
            hard_gate_pass=hard_pass,
            failures=failures,
            metrics=metrics,
            promoted=hard_pass,
            diagnostics=diagnostics,
        )

    def decide_candidate(
        self,
        gate_report: GateReport,
        *,
        model_prob: float,
        no_vig_prob: float,
        live_two_sided_quote: bool,
        data_fresh: bool,
        exposure_limits_ok: bool,
    ) -> CandidateDecision:
        """Apply live-only gates to one candidate after its market has earned OFFICIAL status."""
        canonical = self._market(gate_report.market)
        failures: list[str] = []
        g = self.gates

        model_p = _finite(model_prob, "model_prob")
        market_p = _finite(no_vig_prob, "no_vig_prob")
        if not 0.0 <= model_p <= 1.0 or not 0.0 <= market_p <= 1.0:
            raise TruthGateError("CFB_TRUTH_GATE_CANDIDATE_PROBABILITY_INVALID")
        for value, name in (
            (live_two_sided_quote, "live_two_sided_quote"),
            (data_fresh, "data_fresh"),
            (exposure_limits_ok, "exposure_limits_ok"),
        ):
            if type(value) is not bool:
                raise TruthGateError(f"{name}:BOOL_REQUIRED")

        if not gate_report.hard_gate_pass or gate_report.status != PromotionState.OFFICIAL.value:
            failures.append("MARKET_NOT_OFFICIAL")
        if gate_report.policy_sha256 != self.policy_sha256:
            failures.append("GATE_REPORT_POLICY_HASH_MISMATCH")
        if g["require_live_two_sided_quote"] and not live_two_sided_quote:
            failures.append("LIVE_TWO_SIDED_QUOTE_MISSING")
        if g["require_data_freshness"] and not data_fresh:
            failures.append("DATA_NOT_FRESH")
        if g["require_exposure_limits"] and not exposure_limits_ok:
            failures.append("EXPOSURE_LIMITS_VIOLATED")

        edge = model_p - market_p
        if failures:
            status = CandidateBetStatus.BLOCKED
        elif edge < float(g["edge_floor"]):
            status = CandidateBetStatus.NO_BET
        else:
            status = CandidateBetStatus.OFFICIAL_BET

        return CandidateDecision(
            market=canonical,
            bet_status=status.value,
            policy_id=str(self.policy["policy_id"]),
            policy_sha256=self.policy_sha256,
            edge=edge,
            failures=failures,
        )
