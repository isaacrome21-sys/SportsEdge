"""Frozen MLB promotion-replay policy validation and evidence binding.

This module does not create promotion evidence or change eligibility.  It only
validates the committed replay contract and prevents historical/untouched-holdout
gates from passing unless the evidence is bound to the exact frozen policy bytes.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

EXPECTED_SCHEMA_VERSION = 1
EXPECTED_POLICY_ID = "MLB_REPLAY_POLICY_V1"
EXPECTED_STATUS = "FROZEN_PRE_REPLAY"
EXPECTED_SPORT = "MLB"
REPLAY_BOUND_GATES = ("historical_point_in_time", "untouched_holdout")


class MLBReplayPolicyError(ValueError):
    pass


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise MLBReplayPolicyError(f"MLB_REPLAY_POLICY_DATE_INVALID:{field}") from exc


def _require(condition: bool, error: str) -> None:
    if not condition:
        raise MLBReplayPolicyError(error)


def validate_replay_policy(payload: Mapping[str, Any], *, raw_bytes: bytes) -> dict[str, Any]:
    """Validate the frozen replay contract and return its immutable identity."""
    _require(isinstance(payload, Mapping), "MLB_REPLAY_POLICY_MAPPING_REQUIRED")
    _require(payload.get("schema_version") == EXPECTED_SCHEMA_VERSION, "MLB_REPLAY_POLICY_SCHEMA_MISMATCH")
    _require(payload.get("policy_id") == EXPECTED_POLICY_ID, "MLB_REPLAY_POLICY_ID_MISMATCH")
    _require(payload.get("status") == EXPECTED_STATUS, "MLB_REPLAY_POLICY_NOT_FROZEN")
    _require(payload.get("sport") == EXPECTED_SPORT, "MLB_REPLAY_POLICY_SPORT_MISMATCH")

    governance = payload.get("governance")
    _require(isinstance(governance, Mapping), "MLB_REPLAY_POLICY_GOVERNANCE_REQUIRED")
    _require(governance.get("no_post_result_substitution") is True, "MLB_REPLAY_POLICY_POST_RESULT_SUBSTITUTION_FORBIDDEN")
    _require(governance.get("synthetic_or_ci_waiver_counts_as_evidence") is False, "MLB_REPLAY_POLICY_SYNTHETIC_EVIDENCE_FORBIDDEN")
    _require(bool(str(governance.get("policy_identity_binding") or "").strip()), "MLB_REPLAY_POLICY_IDENTITY_BINDING_REQUIRED")

    calendar = payload.get("season_calendar")
    walk = payload.get("walk_forward")
    _require(isinstance(calendar, Mapping) and isinstance(walk, Mapping), "MLB_REPLAY_POLICY_WINDOWS_REQUIRED")
    replay_start = _date(calendar.get("regular_season_replay_start"), "regular_season_replay_start")
    replay_end = _date(calendar.get("walk_forward_replay_end"), "walk_forward_replay_end")
    holdout_start = _date(calendar.get("untouched_forward_holdout_start"), "untouched_forward_holdout_start")
    holdout_end = _date(calendar.get("untouched_forward_holdout_end"), "untouched_forward_holdout_end")
    _require(replay_start <= replay_end < holdout_start <= holdout_end, "MLB_REPLAY_POLICY_WINDOW_ORDER_INVALID")

    holdout = walk.get("untouched_forward_holdout")
    _require(isinstance(holdout, Mapping), "MLB_REPLAY_POLICY_HOLDOUT_REQUIRED")
    _require(_date(holdout.get("start"), "walk_forward.holdout.start") == holdout_start, "MLB_REPLAY_POLICY_HOLDOUT_START_MISMATCH")
    _require(_date(holdout.get("end"), "walk_forward.holdout.end") == holdout_end, "MLB_REPLAY_POLICY_HOLDOUT_END_MISMATCH")
    _require(holdout.get("fit_max_date_must_be_before_start") is True, "MLB_REPLAY_POLICY_HOLDOUT_FIT_BOUNDARY_REQUIRED")
    _require(holdout.get("may_accumulate_only_after_policy_freeze") is True, "MLB_REPLAY_POLICY_HOLDOUT_FREEZE_REQUIRED")
    _require(walk.get("heldout_outcomes_may_not_change_same_fold_model_or_calibration") is True, "MLB_REPLAY_POLICY_FOLD_LEAKAGE_GUARD_REQUIRED")

    folds = walk.get("folds")
    _require(isinstance(folds, list) and bool(folds), "MLB_REPLAY_POLICY_FOLDS_REQUIRED")
    seen_names: set[str] = set()
    prior_end: date | None = None
    for index, raw in enumerate(folds):
        _require(isinstance(raw, Mapping), f"MLB_REPLAY_POLICY_FOLD_INVALID:{index}")
        name = str(raw.get("name") or "").strip()
        _require(bool(name) and name not in seen_names, f"MLB_REPLAY_POLICY_FOLD_NAME_INVALID:{index}")
        seen_names.add(name)
        train_end = _date(raw.get("train_end"), f"folds[{index}].train_end")
        validation_start = _date(raw.get("validation_start"), f"folds[{index}].validation_start")
        validation_end = _date(raw.get("validation_end"), f"folds[{index}].validation_end")
        _require(train_end < validation_start <= validation_end, f"MLB_REPLAY_POLICY_FOLD_ORDER_INVALID:{name}")
        if prior_end is None:
            _require(validation_start == replay_start, "MLB_REPLAY_POLICY_FIRST_FOLD_START_MISMATCH")
        else:
            _require(validation_start == prior_end + timedelta(days=1), f"MLB_REPLAY_POLICY_FOLD_GAP_OR_OVERLAP:{name}")
        prior_end = validation_end
    _require(prior_end == replay_end, "MLB_REPLAY_POLICY_LAST_FOLD_END_MISMATCH")

    benchmark = payload.get("benchmark")
    _require(isinstance(benchmark, Mapping), "MLB_REPLAY_POLICY_BENCHMARK_REQUIRED")
    _require(int(benchmark.get("quote_max_age_seconds", -1)) == 180, "MLB_REPLAY_POLICY_QUOTE_AGE_MISMATCH")
    _require(int(benchmark.get("paired_side_max_timestamp_skew_seconds", -1)) == 30, "MLB_REPLAY_POLICY_PAIR_SKEW_MISMATCH")
    devig = benchmark.get("devig")
    _require(isinstance(devig, Mapping), "MLB_REPLAY_POLICY_DEVIG_REQUIRED")
    _require(devig.get("method") == "MULTIPLICATIVE_V1" and devig.get("two_sided_only") is True, "MLB_REPLAY_POLICY_DEVIG_MISMATCH")
    _require(devig.get("n_way_devig_not_authorized_by_this_policy") is True, "MLB_REPLAY_POLICY_NWAY_GUARD_REQUIRED")

    coverage = payload.get("coverage_and_promotion")
    _require(isinstance(coverage, Mapping), "MLB_REPLAY_POLICY_PROMOTION_REQUIRED")
    _require(coverage.get("official_promotion_requires_existing_truth_gate_plus_this_policy") is True, "MLB_REPLAY_POLICY_TRUTH_GATE_BINDING_REQUIRED")
    _require(coverage.get("replay_before_policy_freeze_counts_toward_official") is False, "MLB_REPLAY_POLICY_PREFREEZE_EVIDENCE_FORBIDDEN")

    return {
        "policy_id": EXPECTED_POLICY_ID,
        "policy_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "status": EXPECTED_STATUS,
        "effective_date": str(payload.get("effective_date") or ""),
        "replay_start": replay_start.isoformat(),
        "replay_end": replay_end.isoformat(),
        "untouched_holdout_start": holdout_start.isoformat(),
        "untouched_holdout_end": holdout_end.isoformat(),
    }


def load_replay_policy(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MLBReplayPolicyError("MLB_REPLAY_POLICY_UNREADABLE") from exc
    return validate_replay_policy(payload, raw_bytes=raw)


def enforce_replay_policy_binding(
    markets: Mapping[str, Mapping[str, Mapping[str, Any]]],
    *,
    policy_identity: Mapping[str, Any],
    as_of_date: date,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Fail closed if replay-bound PASS gates lack exact policy identity.

    The untouched holdout is additionally prohibited from passing until the frozen
    holdout window has completely elapsed.  This function never upgrades a gate.
    """
    out = deepcopy(dict(markets))
    expected_id = str(policy_identity["policy_id"])
    expected_sha = str(policy_identity["policy_sha256"])
    holdout_end = _date(policy_identity["untouched_holdout_end"], "identity.untouched_holdout_end")
    for market, gates in out.items():
        if not isinstance(gates, dict):
            continue
        for gate_name in REPLAY_BOUND_GATES:
            gate = gates.get(gate_name)
            if not isinstance(gate, dict) or gate.get("status") != "PASS":
                continue
            if gate_name == "untouched_holdout" and as_of_date <= holdout_end:
                gates[gate_name] = {
                    **gate,
                    "status": "FAIL",
                    "reason": "MLB_REPLAY_UNTOUCHED_HOLDOUT_WINDOW_INCOMPLETE",
                    "required_complete_after": holdout_end.isoformat(),
                }
                continue
            if gate.get("replay_policy_id") != expected_id or gate.get("replay_policy_sha256") != expected_sha:
                gates[gate_name] = {
                    **gate,
                    "status": "FAIL",
                    "reason": "MLB_REPLAY_POLICY_BINDING_MISSING_OR_MISMATCH",
                    "required_replay_policy_id": expected_id,
                    "required_replay_policy_sha256": expected_sha,
                }
    return out
