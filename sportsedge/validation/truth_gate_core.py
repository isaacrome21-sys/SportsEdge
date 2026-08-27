from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .gate_report import GateReport


class TruthGatePolicyError(ValueError):
    pass


class EvidenceError(ValueError):
    pass


class MarketStatus:
    NO_ENGINE = "NO_ENGINE"
    EXPERIMENTAL = "EXPERIMENTAL"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    VALIDATED_MODEL = "VALIDATED_MODEL"
    READY_FOR_POLICY = "READY_FOR_POLICY"
    OFFICIAL = "OFFICIAL"
    REVOKED = "REVOKED"


class CandidateDecision:
    OFFICIAL_BET = "OFFICIAL_BET"
    NO_BET = "NO_BET"
    BLOCKED = "BLOCKED"


class TruthGateCore:
    REQUIRED_HARD_KEYS = frozenset({
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
        "require_live_two_sided_quote",
        "require_data_freshness",
        "require_frozen_policy_hash",
        "edge_floor",
        "require_exposure_limits",
    })

    def __init__(self, policy_path: str | Path):
        self.policy_path = Path(policy_path)
        try:
            raw = self.policy_path.read_bytes()
        except OSError as exc:
            raise TruthGatePolicyError(f"POLICY_UNREADABLE:{self.policy_path}") from exc
        try:
            policy = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise TruthGatePolicyError("POLICY_JSON_INVALID") from exc
        if not isinstance(policy, dict):
            raise TruthGatePolicyError("POLICY_OBJECT_REQUIRED")
        if not isinstance(policy.get("hard_gates"), dict):
            raise TruthGatePolicyError("POLICY_HARD_GATES_OBJECT_REQUIRED")

        self.policy = policy
        self.policy_sha256 = hashlib.sha256(raw).hexdigest()
        self.gates = dict(policy["hard_gates"])

        missing = self.REQUIRED_HARD_KEYS - self.gates.keys()
        if missing:
            raise TruthGatePolicyError(
                "POLICY_FIELDS_MISSING:" + ",".join(sorted(missing))
            )

        policy_id = policy.get("policy_id")
        version = policy.get("version")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise TruthGatePolicyError("POLICY_ID_REQUIRED")
        if not isinstance(version, str) or not version.strip():
            raise TruthGatePolicyError("POLICY_VERSION_REQUIRED")

        identity = (
            policy.get("markets")
            if policy.get("markets") is not None
            else policy.get("market_families")
            if policy.get("market_families") is not None
            else policy.get("surfaces")
        )
        if not isinstance(identity, list) or not identity:
            raise TruthGatePolicyError("POLICY_MARKET_IDENTITY_REQUIRED")
        self.allowed_markets = frozenset(self._canonical_market(x) for x in identity)
        if "" in self.allowed_markets:
            raise TruthGatePolicyError("POLICY_MARKET_IDENTITY_INVALID")

        overrides = policy.get("family_overrides", {})
        if not isinstance(overrides, dict):
            raise TruthGatePolicyError("POLICY_FAMILY_OVERRIDES_OBJECT_REQUIRED")
        self.family_overrides = overrides
        self.diagnostics_cfg = policy.get("diagnostics_only", {})
        if not isinstance(self.diagnostics_cfg, dict):
            raise TruthGatePolicyError("POLICY_DIAGNOSTICS_OBJECT_REQUIRED")

        self._validate_policy_types()

    @staticmethod
    def _canonical_market(value: Any) -> str:
        return str(value or "").strip().upper()

    @staticmethod
    def _finite_number(value: Any, name: str) -> float:
        if isinstance(value, bool):
            raise EvidenceError(f"{name}:NUMERIC_REQUIRED")
        try:
            out = float(value)
        except (TypeError, ValueError) as exc:
            raise EvidenceError(f"{name}:NUMERIC_REQUIRED") from exc
        if not math.isfinite(out):
            raise EvidenceError(f"{name}:FINITE_REQUIRED")
        return out

    @staticmethod
    def _nonnegative_int(value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise EvidenceError(f"{name}:NONNEGATIVE_INTEGER_REQUIRED")
        if value < 0:
            raise EvidenceError(f"{name}:NONNEGATIVE_INTEGER_REQUIRED")
        return value

    @staticmethod
    def _strict_bool(value: Any, name: str) -> bool:
        if type(value) is not bool:
            raise EvidenceError(f"{name}:BOOL_REQUIRED")
        return value

    def _validate_policy_types(self) -> None:
        int_keys = (
            "max_leakage_violations",
            "min_forward_seasons",
            "target_forward_seasons",
            "min_promoted_sample_absolute",
            "preferred_promoted_sample",
        )
        for key in int_keys:
            value = self.gates[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise TruthGatePolicyError(f"POLICY_{key.upper()}_NONNEGATIVE_INTEGER_REQUIRED")

        bool_keys = (
            "pit_reproducibility_required",
            "brier_must_beat_market",
            "logloss_must_beat_market",
            "recent_two_season_deterioration_allowed",
            "require_live_two_sided_quote",
            "require_data_freshness",
            "require_frozen_policy_hash",
            "require_exposure_limits",
        )
        for key in bool_keys:
            if type(self.gates[key]) is not bool:
                raise TruthGatePolicyError(f"POLICY_{key.upper()}_BOOL_REQUIRED")

        numeric_keys = (
            "min_season_fold_scoring_win_rate",
            "min_mean_novig_clv",
            "min_clv_t_stat",
            "min_roi_after_vig",
            "target_roi_after_vig",
            "calibration_slope_min",
            "calibration_slope_max",
            "calibration_intercept_abs_max",
            "max_ece",
            "edge_floor",
        )
        for key in numeric_keys:
            try:
                value = self._finite_number(self.gates[key], key)
            except EvidenceError as exc:
                raise TruthGatePolicyError(f"POLICY_{str(exc)}") from exc
            if key in {
                "min_season_fold_scoring_win_rate",
                "max_ece",
                "edge_floor",
            } and not 0.0 <= value <= 1.0:
                raise TruthGatePolicyError(f"POLICY_{key.upper()}_PROBABILITY_REQUIRED")

        if self.gates["min_forward_seasons"] > self.gates["target_forward_seasons"]:
            raise TruthGatePolicyError("POLICY_FORWARD_SEASON_TARGET_INVALID")
        if self.gates["min_promoted_sample_absolute"] > self.gates["preferred_promoted_sample"]:
            raise TruthGatePolicyError("POLICY_SAMPLE_TARGET_INVALID")
        if float(self.gates["calibration_slope_min"]) > float(self.gates["calibration_slope_max"]):
            raise TruthGatePolicyError("POLICY_CALIBRATION_SLOPE_RANGE_INVALID")

        for market, override in self.family_overrides.items():
            canonical = self._canonical_market(market)
            if canonical not in self.allowed_markets:
                raise TruthGatePolicyError(f"POLICY_OVERRIDE_MARKET_UNSUPPORTED:{canonical}")
            if not isinstance(override, dict):
                raise TruthGatePolicyError(f"POLICY_OVERRIDE_OBJECT_REQUIRED:{canonical}")
            unknown = set(override) - {"edge_floor"}
            if unknown:
                raise TruthGatePolicyError(
                    f"POLICY_OVERRIDE_FIELDS_UNSUPPORTED:{canonical}:" + ",".join(sorted(unknown))
                )
            if "edge_floor" in override:
                try:
                    floor = self._finite_number(override["edge_floor"], f"{canonical}.edge_floor")
                except EvidenceError as exc:
                    raise TruthGatePolicyError(f"POLICY_{str(exc)}") from exc
                if not 0.0 <= floor <= 1.0:
                    raise TruthGatePolicyError(f"POLICY_OVERRIDE_EDGE_FLOOR_INVALID:{canonical}")

    def edge_floor(self, market: str) -> float:
        canonical = self._canonical_market(market)
        override = self.family_overrides.get(canonical, {})
        return float(override["edge_floor"]) if "edge_floor" in override else float(self.gates["edge_floor"])

    def _early_failure_report(
        self,
        *,
        sport: str,
        market: str,
        market_failures: list[str],
        metrics: Mapping[str, Any] | None = None,
    ) -> GateReport:
        return GateReport(
            sport=sport,
            market=market,
            market_status=MarketStatus.EVIDENCE_INCOMPLETE,
            candidate_decision=CandidateDecision.BLOCKED,
            policy_version=str(self.policy["version"]),
            policy_sha256=self.policy_sha256,
            hard_gate_pass=False,
            market_failures=tuple(market_failures),
            candidate_failures=("MARKET_NOT_CERTIFIED",),
            metrics=tuple(sorted((metrics or {}).items())),
            diagnostics=(),
            edge=None,
            notes=(),
        )

    def evaluate(self, sport: str, market: str, **kwargs: Any) -> GateReport:
        sport_name = str(sport or "").strip().upper()
        canonical = self._canonical_market(market)
        market_failures: list[str] = []
        candidate_failures: list[str] = []

        if not sport_name:
            market_failures.append("SPORT_IDENTITY_MISSING")
        if canonical not in self.allowed_markets:
            market_failures.append("INVALID_MARKET_OR_FAMILY")

        evidence_market = self._canonical_market(kwargs.get("evidence_market"))
        if evidence_market != canonical:
            market_failures.append("EVIDENCE_MARKET_IDENTITY_MISMATCH")

        if self.gates["require_frozen_policy_hash"]:
            if kwargs.get("evidence_policy_sha256") != self.policy_sha256:
                market_failures.append("POLICY_SHA256_MISMATCH")

        metrics: dict[str, Any] = {}
        try:
            metrics["brier_model"] = self._finite_number(kwargs.get("brier_model"), "brier_model")
            metrics["brier_market"] = self._finite_number(kwargs.get("brier_market"), "brier_market")
            metrics["logloss_model"] = self._finite_number(kwargs.get("logloss_model"), "logloss_model")
            metrics["logloss_market"] = self._finite_number(kwargs.get("logloss_market"), "logloss_market")
            metrics["season_fold_scoring_win_rate"] = self._finite_number(
                kwargs.get("season_fold_scoring_win_rate"),
                "season_fold_scoring_win_rate",
            )
            metrics["mean_novig_clv"] = self._finite_number(kwargs.get("mean_novig_clv"), "mean_novig_clv")
            metrics["clv_t_stat"] = self._finite_number(kwargs.get("clv_t_stat"), "clv_t_stat")
            metrics["roi_after_vig"] = self._finite_number(kwargs.get("roi_after_vig"), "roi_after_vig")
            metrics["calibration_slope"] = self._finite_number(kwargs.get("calibration_slope"), "calibration_slope")
            metrics["calibration_intercept"] = self._finite_number(
                kwargs.get("calibration_intercept"),
                "calibration_intercept",
            )
            metrics["ece"] = self._finite_number(kwargs.get("ece"), "ece")
            metrics["n_promoted"] = self._nonnegative_int(kwargs.get("n_promoted"), "n_promoted")
            metrics["n_forward_seasons"] = self._nonnegative_int(
                kwargs.get("n_forward_seasons"),
                "n_forward_seasons",
            )
            metrics["leakage_violations"] = self._nonnegative_int(
                kwargs.get("leakage_violations"),
                "leakage_violations",
            )
            pit_reproducible = self._strict_bool(kwargs.get("pit_reproducible"), "pit_reproducible")
            recent_two_season_ok = self._strict_bool(
                kwargs.get("recent_two_season_ok"),
                "recent_two_season_ok",
            )
        except EvidenceError as exc:
            market_failures.append(str(exc))
            return self._early_failure_report(
                sport=sport_name,
                market=canonical,
                market_failures=market_failures,
                metrics=metrics,
            )

        fold_rate = metrics["season_fold_scoring_win_rate"]
        ece = metrics["ece"]
        if not 0.0 <= fold_rate <= 1.0:
            market_failures.append("SEASON_FOLD_SCORING_WIN_RATE_OUT_OF_BOUNDS")
        if not 0.0 <= ece <= 1.0:
            market_failures.append("ECE_OUT_OF_BOUNDS")

        g = self.gates
        if g["pit_reproducibility_required"] and not pit_reproducible:
            market_failures.append("PIT_REPRODUCIBILITY_FAILED")
        if metrics["leakage_violations"] > g["max_leakage_violations"]:
            market_failures.append("LEAKAGE_VIOLATIONS_EXCEEDED")
        if metrics["n_forward_seasons"] < g["min_forward_seasons"]:
            market_failures.append("FORWARD_SEASONS_BELOW_FLOOR")
        if g["brier_must_beat_market"] and metrics["brier_model"] >= metrics["brier_market"]:
            market_failures.append("BRIER_DOES_NOT_BEAT_MARKET")
        if g["logloss_must_beat_market"] and metrics["logloss_model"] >= metrics["logloss_market"]:
            market_failures.append("LOGLOSS_DOES_NOT_BEAT_MARKET")
        if metrics["season_fold_scoring_win_rate"] < g["min_season_fold_scoring_win_rate"]:
            market_failures.append("SEASON_FOLD_SCORING_WIN_RATE_BELOW_FLOOR")
        if metrics["mean_novig_clv"] < g["min_mean_novig_clv"]:
            market_failures.append("MEAN_NOVIG_CLV_BELOW_FLOOR")
        if metrics["clv_t_stat"] < g["min_clv_t_stat"]:
            market_failures.append("CLV_T_STAT_BELOW_FLOOR")
        if metrics["roi_after_vig"] <= g["min_roi_after_vig"]:
            market_failures.append("ROI_AFTER_VIG_NOT_POSITIVE")
        if not g["calibration_slope_min"] <= metrics["calibration_slope"] <= g["calibration_slope_max"]:
            market_failures.append("CALIBRATION_SLOPE_OUT_OF_RANGE")
        if abs(metrics["calibration_intercept"]) > g["calibration_intercept_abs_max"]:
            market_failures.append("CALIBRATION_INTERCEPT_OUT_OF_RANGE")
        if metrics["ece"] > g["max_ece"]:
            market_failures.append("ECE_ABOVE_MAX")
        if metrics["n_promoted"] < g["min_promoted_sample_absolute"]:
            market_failures.append("PROMOTED_SAMPLE_BELOW_ABSOLUTE_FLOOR")
        if not recent_two_season_ok and not g["recent_two_season_deterioration_allowed"]:
            market_failures.append("RECENT_TWO_SEASON_DETERIORATION")

        if g.get("require_coherent_joint_constraints", False):
            coherent_value = kwargs.get("coherent_joint")
            if type(coherent_value) is not bool:
                market_failures.append("coherent_joint:BOOL_REQUIRED")
                market_failures.append("JOINT_COHERENCE_FAILED")
            elif not coherent_value:
                market_failures.append("JOINT_COHERENCE_FAILED")

        if g.get("require_shared_path_coherence", False):
            shared_value = kwargs.get("shared_path_ok")
            if type(shared_value) is not bool:
                market_failures.append("shared_path_ok:BOOL_REQUIRED")
                market_failures.append("SHARED_PATH_COHERENCE_FAILED")
            elif not shared_value:
                market_failures.append("SHARED_PATH_COHERENCE_FAILED")

        sport_specific = kwargs.get("sport_specific_failures") or {}
        if not isinstance(sport_specific, Mapping):
            market_failures.append("SPORT_SPECIFIC_FAILURES_MAPPING_REQUIRED")
        else:
            for flag, reason in sorted(sport_specific.items(), key=lambda item: str(item[0])):
                if type(flag) is not bool:
                    market_failures.append("SPORT_SPECIFIC_FAILURE_FLAG_BOOL_REQUIRED")
                    continue
                if flag:
                    reason_text = str(reason or "").strip()
                    market_failures.append(reason_text or "SPORT_SPECIFIC_EVIDENCE_FAILED")

        market_pass = not market_failures

        if market_pass:
            market_status = MarketStatus.OFFICIAL
        elif (
            metrics["n_promoted"] < g["min_promoted_sample_absolute"]
            or metrics["n_forward_seasons"] < g["min_forward_seasons"]
            or "POLICY_SHA256_MISMATCH" in market_failures
            or "EVIDENCE_MARKET_IDENTITY_MISMATCH" in market_failures
        ):
            market_status = MarketStatus.EVIDENCE_INCOMPLETE
        else:
            market_status = MarketStatus.EXPERIMENTAL

        edge: float | None = None
        candidate = CandidateDecision.NO_BET
        if not market_pass:
            candidate = CandidateDecision.BLOCKED
            candidate_failures.append("MARKET_NOT_CERTIFIED")
        else:
            live_ok = True
            try:
                model_prob = self._finite_number(kwargs.get("model_prob"), "model_prob")
                no_vig_prob = self._finite_number(kwargs.get("no_vig_prob"), "no_vig_prob")
                if not 0.0 <= model_prob <= 1.0 or not 0.0 <= no_vig_prob <= 1.0:
                    raise EvidenceError("LIVE_PROB_OUT_OF_BOUNDS")
            except EvidenceError as exc:
                candidate_failures.append(str(exc))
                live_ok = False
                model_prob = None
                no_vig_prob = None

            try:
                live_quote = self._strict_bool(
                    kwargs.get("live_two_sided_quote"),
                    "live_two_sided_quote",
                )
                data_fresh = self._strict_bool(kwargs.get("data_fresh"), "data_fresh")
                exposure_ok = self._strict_bool(
                    kwargs.get("exposure_limits_ok"),
                    "exposure_limits_ok",
                )
            except EvidenceError as exc:
                candidate_failures.append(str(exc))
                live_ok = False
                live_quote = data_fresh = exposure_ok = False

            if g["require_live_two_sided_quote"] and not live_quote:
                candidate_failures.append("LIVE_TWO_SIDED_QUOTE_MISSING")
                live_ok = False
            if g["require_data_freshness"] and not data_fresh:
                candidate_failures.append("DATA_NOT_FRESH")
                live_ok = False
            if g["require_exposure_limits"] and not exposure_ok:
                candidate_failures.append("EXPOSURE_LIMITS_VIOLATED")
                live_ok = False

            if not live_ok:
                candidate = CandidateDecision.BLOCKED
            else:
                edge = float(model_prob) - float(no_vig_prob)
                candidate = (
                    CandidateDecision.OFFICIAL_BET
                    if edge >= self.edge_floor(canonical)
                    else CandidateDecision.NO_BET
                )

        diagnostics: dict[str, Any] = {
            "target_forward_seasons": g["target_forward_seasons"],
            "preferred_promoted_sample": g["preferred_promoted_sample"],
            "target_roi_after_vig": g["target_roi_after_vig"],
        }
        hit_rates = kwargs.get("hit_rates")
        if isinstance(hit_rates, Mapping):
            for key, value in sorted(hit_rates.items(), key=lambda item: str(item[0])):
                try:
                    diagnostics[f"hit_rate.{key}"] = self._finite_number(value, f"hit_rates.{key}")
                except EvidenceError:
                    continue
        targets = self.diagnostics_cfg.get("hit_rate_buckets", {})
        if isinstance(targets, Mapping):
            for key, value in sorted(targets.items(), key=lambda item: str(item[0])):
                diagnostics[f"hit_rate_target.{key}"] = value

        return GateReport(
            sport=sport_name,
            market=canonical,
            market_status=market_status,
            candidate_decision=candidate,
            policy_version=str(self.policy["version"]),
            policy_sha256=self.policy_sha256,
            hard_gate_pass=market_pass,
            market_failures=tuple(market_failures),
            candidate_failures=tuple(candidate_failures),
            metrics=tuple(sorted(metrics.items())),
            diagnostics=tuple(sorted(diagnostics.items())),
            edge=edge,
            notes=(),
        )
