"""Fail-closed readiness gate for the reconstructed CFB candidate-selection lane.

Candidate selection is intentionally separate from promotion evidence.  Reconstructed
historical data may be used to choose/freeze a serving contract, but it never creates
historical PIT evidence, Model_P authority, Truth Gate authority, or OFFICIAL bets.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

CFB_SELECTION_READINESS_VERSION = "CFB_FIRST_EVALUATION_READINESS_V2"
RECONSTRUCTED_PROVENANCE = "RECONSTRUCTED_HISTORICAL_NOT_PIT"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_sha(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value.strip().lower()) is not None


def _expected_training_window(preregistration: Mapping[str, Any]) -> tuple[int | None, int | None, list[str]]:
    blockers: list[str] = []
    candidates = preregistration.get("candidates")
    if not isinstance(candidates, Mapping) or not candidates:
        return None, None, ["CANDIDATE_PREREGISTRATION_MISSING"]
    windows: set[tuple[int, int]] = set()
    for family, raw in candidates.items():
        if not isinstance(raw, Mapping):
            blockers.append(f"CANDIDATE_SPEC_INVALID:{family}")
            continue
        window = raw.get("training_window")
        if not isinstance(window, Mapping):
            blockers.append(f"TRAINING_WINDOW_MISSING:{family}")
            continue
        try:
            start = int(window.get("start_season"))
            end = int(window.get("end_season"))
        except (TypeError, ValueError):
            blockers.append(f"TRAINING_WINDOW_INVALID:{family}")
            continue
        windows.add((start, end))
        if window.get("no_2026_forward_outcomes") is not True:
            blockers.append(f"FORWARD_OUTCOME_GUARD_MISSING:{family}")
    if len(windows) != 1:
        blockers.append("CANDIDATE_TRAINING_WINDOWS_NOT_IDENTICAL")
        return None, None, blockers
    start, end = next(iter(windows))
    return start, end, blockers


def audit_cfb_selection_readiness(
    *,
    policy: Mapping[str, Any],
    preregistration: Mapping[str, Any],
    prereg_report: Mapping[str, Any],
    freeze_registry: Mapping[str, Any],
    acquisition_report: Mapping[str, Any],
    selection_bundle: Mapping[str, Any] | None,
) -> dict[str, Any]:
    blockers: list[str] = []

    if policy.get("schema") != "CFB_MODEL_SELECTION_POLICY_V1":
        blockers.append("SELECTION_POLICY_SCHEMA_MISMATCH")
    if policy.get("status") != "FROZEN_BEFORE_CANDIDATE_EVALUATION":
        blockers.append("SELECTION_POLICY_NOT_FROZEN")
    if policy.get("training_provenance_class") != RECONSTRUCTED_PROVENANCE:
        blockers.append("SELECTION_POLICY_PROVENANCE_CLASS_INVALID")

    if freeze_registry.get("training_provenance_class_required") != RECONSTRUCTED_PROVENANCE:
        blockers.append("FREEZE_REGISTRY_PROVENANCE_CLASS_INVALID")
    if freeze_registry.get("promotion_authority") is not False:
        blockers.append("FREEZE_REGISTRY_PROMOTION_AUTHORITY_MUST_BE_FALSE")
    if freeze_registry.get("evidence_clock_authority") is not False:
        blockers.append("FREEZE_REGISTRY_EVIDENCE_CLOCK_AUTHORITY_MUST_BE_FALSE")

    governance = preregistration.get("governance") or {}
    if governance.get("attempts_consumed") != 0:
        blockers.append("FIRST_EVALUATION_REQUIRES_ZERO_ATTEMPTS_CONSUMED")
    if governance.get("evaluation_performed") is not False:
        blockers.append("FIRST_EVALUATION_REQUIRES_NO_PRIOR_EVALUATION")
    for key in ("model_p_created", "promotion_authority", "eligibility_changed", "official_authority"):
        if governance.get(key) is not False:
            blockers.append(f"PREREG_AUTHORITY_FORBIDDEN:{key}")

    prereg_ready = prereg_report.get("status") == "READY_FOR_FIRST_EVALUATION"
    if not prereg_ready:
        blockers.append("PREREGISTRATION_NOT_READY")

    acquisition_ready = acquisition_report.get("status") == "READY_FOR_HISTORICAL_REPLAY"
    if not acquisition_ready:
        blockers.append("RECONSTRUCTED_ACQUISITION_NOT_READY")
        blockers.extend(acquisition_report.get("blockers") or [])
    for key in ("attempt_consumed", "model_fit_performed", "model_p_created", "promotion_authority", "eligibility_changed"):
        if acquisition_report.get(key) is not False:
            blockers.append(f"ACQUISITION_AUTHORITY_OR_ATTEMPT_LEAK:{key}")

    start_season, end_season, window_blockers = _expected_training_window(preregistration)
    blockers.extend(window_blockers)

    bundle_ready = False
    if not isinstance(selection_bundle, Mapping):
        blockers.append("RECONSTRUCTED_SELECTION_BUNDLE_MISSING")
    else:
        if selection_bundle.get("schema") != "CFB_RECONSTRUCTED_SELECTION_BUNDLE_V1":
            blockers.append("SELECTION_BUNDLE_SCHEMA_MISMATCH")
        if selection_bundle.get("status") != "READY_FOR_CANDIDATE_EVALUATION":
            blockers.append("SELECTION_BUNDLE_STATUS_NOT_READY")
        expected = {
            "provenance_class": policy.get("training_provenance_class"),
            "feature_semantics": policy.get("feature_semantics"),
            "feature_value_source_contract": policy.get("feature_value_source_contract"),
            "provider_metric_model_vintage": policy.get("provider_metric_model_vintage"),
            "provider_metric_materialization_mode": policy.get("provider_metric_materialization_mode"),
        }
        for key, value in expected.items():
            if selection_bundle.get(key) != value:
                blockers.append(f"SELECTION_BUNDLE_CONTRACT_MISMATCH:{key}")
        if start_season is not None and selection_bundle.get("start_season") != start_season:
            blockers.append("SELECTION_BUNDLE_START_SEASON_MISMATCH")
        if end_season is not None and selection_bundle.get("end_season") != end_season:
            blockers.append("SELECTION_BUNDLE_END_SEASON_MISMATCH")
        if selection_bundle.get("no_2026_forward_outcomes") is not True:
            blockers.append("SELECTION_BUNDLE_FORWARD_OUTCOME_GUARD_MISSING")
        if selection_bundle.get("market_data_in_predictive_features") is not False:
            blockers.append("SELECTION_BUNDLE_MARKET_CONTAMINATION")
        for key in (
            "selection_rows_sha256",
            "source_manifest_sha256",
            "predictive_code_manifest_sha256",
            "acquisition_code_manifest_sha256",
        ):
            if not _valid_sha(selection_bundle.get(key)):
                blockers.append(f"SELECTION_BUNDLE_HASH_INVALID:{key}")

        candidate_features = {
            str(feature)
            for raw in (preregistration.get("candidates") or {}).values()
            if isinstance(raw, Mapping)
            for feature in (raw.get("feature_list") or [])
        }
        if {"wind_speed", "temperature"} & candidate_features:
            weather_class = selection_bundle.get("weather_provenance_class")
            if weather_class not in {RECONSTRUCTED_PROVENANCE, "PRE_EVENT_ARCHIVE"}:
                blockers.append("SELECTION_BUNDLE_WEATHER_PROVENANCE_UNRESOLVED")
            if not _nonempty(selection_bundle.get("weather_source_contract")):
                blockers.append("SELECTION_BUNDLE_WEATHER_SOURCE_CONTRACT_MISSING")
        bundle_ready = not any(item.startswith("SELECTION_BUNDLE_") for item in blockers)

    allowed = prereg_ready and acquisition_ready and bundle_ready and not blockers
    unique_blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": CFB_SELECTION_READINESS_VERSION,
        "status": "FIRST_EVALUATION_ALLOWED" if allowed else "BLOCKED_RECONSTRUCTED_SELECTION_CONTRACT",
        "first_evaluation_allowed": allowed,
        "selection_lane": RECONSTRUCTED_PROVENANCE,
        "historical_pit_required_for_selection": False,
        "promotion_evidence_gate": "SEPARATE_DOWNSTREAM_GATE_NOT_EVALUATED_HERE",
        "preregistration_ready": prereg_ready,
        "reconstructed_acquisition_ready": acquisition_ready,
        "reconstructed_selection_bundle_ready": bundle_ready,
        "attempts_consumed": 0,
        "evaluation_performed": False,
        "historical_pit_created": False,
        "model_p_created": False,
        "promotion_authority": False,
        "evidence_clock_authority": False,
        "eligibility_changed": False,
        "official_authority": False,
        "blockers": unique_blockers,
        "do_not_consume_attempt_until_reconstructed_selection_bundle_ready": True,
    }


__all__ = ["audit_cfb_selection_readiness", "CFB_SELECTION_READINESS_VERSION"]
