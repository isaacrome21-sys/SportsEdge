#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

_POLICY_ID = "NFL_V2J_POSTRUN_ADJUDICATION_V1"
_MARKETS = ("spread", "total")
_ZERO_AUTHORITY_FIELDS = (
    "promotion_eligible",
    "promotion_authority",
    "model_p_authority",
    "official_status_granted",
    "production_registry_consumes_this_artifact",
)


def _sha(value: Any, *, length: int, label: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != length or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError(f"NFL_V2J_ADJUDICATION_{label}_INVALID")
    return text


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_zero_authority(payload: Mapping[str, Any], *, label: str) -> None:
    for field in _ZERO_AUTHORITY_FIELDS:
        if payload.get(field) is not False:
            raise ValueError(f"NFL_V2J_ADJUDICATION_{label}_AUTHORITY_INVALID:{field}")


def _policy(policy: Mapping[str, Any]) -> tuple[dict[str, float], float]:
    if policy.get("policy_id") != _POLICY_ID or policy.get("status") != "FROZEN_PRE_READOUT":
        raise ValueError("NFL_V2J_ADJUDICATION_POLICY_INVALID")
    gates = policy.get("frozen_gates")
    if not isinstance(gates, Mapping) or gates.get("all_required") is not True:
        raise ValueError("NFL_V2J_ADJUDICATION_POLICY_GATES_INVALID")
    if tuple(int(x) for x in gates.get("signed_keys", ())) != (-7, -3, 3, 7):
        raise ValueError("NFL_V2J_ADJUDICATION_POLICY_SIGNED_KEYS_INVALID")
    thresholds = {
        "spread_fold": float(gates["spread_fold_win_rate_min"]),
        "total_fold": float(gates["total_fold_win_rate_min"]),
        "spread_calibration": float(gates["spread_calibration_max_bin_deviation"]),
        "total_calibration": float(gates["total_calibration_max_bin_deviation"]),
    }
    key_tolerance = float(gates["signed_key_max_abs_error"])
    if thresholds != {
        "spread_fold": 0.65,
        "total_fold": 0.65,
        "spread_calibration": 0.05,
        "total_calibration": 0.05,
    } or abs(key_tolerance - 0.005) > 1e-12:
        raise ValueError("NFL_V2J_ADJUDICATION_POLICY_THRESHOLD_DRIFT")
    authority = policy.get("authority")
    if not isinstance(authority, Mapping):
        raise ValueError("NFL_V2J_ADJUDICATION_POLICY_AUTHORITY_MISSING")
    for field in (
        "model_p_authority",
        "promotion_authority",
        "staking_authority",
        "official_authority",
        "production_registry_authority",
        "nfl_m2_freeze_authorized",
        "v2k_automatically_activated",
    ):
        if authority.get(field) is not False:
            raise ValueError(f"NFL_V2J_ADJUDICATION_POLICY_AUTHORITY_INVALID:{field}")
    return thresholds, key_tolerance


def adjudicate(
    first_readout: Mapping[str, Any],
    key_math: Mapping[str, Any],
    policy: Mapping[str, Any],
    *,
    upstream_run_id: int,
    upstream_head_sha: str,
    adjudicator_git_sha: str,
    first_readout_sha256: str,
    key_math_sha256: str,
    policy_sha256: str,
) -> dict[str, Any]:
    thresholds, key_tolerance = _policy(policy)
    if first_readout.get("status") != "FIRST_READOUT_DIAGNOSTIC_ONLY":
        raise ValueError("NFL_V2J_ADJUDICATION_READOUT_STATUS_INVALID")
    if first_readout.get("preregistration_locked") is not True:
        raise ValueError("NFL_V2J_ADJUDICATION_PREREGISTRATION_NOT_LOCKED")
    if first_readout.get("post_readout_retuning_allowed") is not False:
        raise ValueError("NFL_V2J_ADJUDICATION_RETUNING_NOT_FORBIDDEN")
    _require_zero_authority(first_readout, label="READOUT")

    if key_math.get("status") != "FIRST_READOUT_DIAGNOSTIC_ONLY":
        raise ValueError("NFL_V2J_ADJUDICATION_KEY_MATH_STATUS_INVALID")
    for field in _ZERO_AUTHORITY_FIELDS:
        if key_math.get(field) is not False:
            raise ValueError(f"NFL_V2J_ADJUDICATION_KEY_MATH_AUTHORITY_INVALID:{field}")

    historical = first_readout.get("candidate_historical_evidence")
    if not isinstance(historical, Mapping):
        raise ValueError("NFL_V2J_ADJUDICATION_HISTORICAL_EVIDENCE_MISSING")

    market_gates: dict[str, dict[str, Any]] = {}
    for market in _MARKETS:
        row = historical.get(market)
        if not isinstance(row, Mapping):
            raise ValueError(f"NFL_V2J_ADJUDICATION_MARKET_EVIDENCE_MISSING:{market}")
        expected_fold = thresholds[f"{market}_fold"]
        required = float(row.get("required_fold_win_rate", -1.0))
        if abs(required - expected_fold) > 1e-12:
            raise ValueError(f"NFL_V2J_ADJUDICATION_FOLD_THRESHOLD_DRIFT:{market}")
        rate = float(row.get("fold_win_rate", -1.0))
        predictive_pass = row.get("historical_predictive_pass") is True
        if predictive_pass != (rate >= expected_fold):
            raise ValueError(f"NFL_V2J_ADJUDICATION_PREDICTIVE_FLAG_MISMATCH:{market}")
        calibration = row.get("calibration")
        if not isinstance(calibration, Mapping):
            raise ValueError(f"NFL_V2J_ADJUDICATION_CALIBRATION_MISSING:{market}")
        expected_calibration = thresholds[f"{market}_calibration"]
        calibration_threshold = float(calibration.get("threshold", -1.0))
        if abs(calibration_threshold - expected_calibration) > 1e-12:
            raise ValueError(f"NFL_V2J_ADJUDICATION_CALIBRATION_THRESHOLD_DRIFT:{market}")
        calibration_pass = calibration.get("pass") is True
        market_gates[market] = {
            "fold_win_rate": rate,
            "required_fold_win_rate": expected_fold,
            "historical_predictive_pass": predictive_pass,
            "calibration_pass": calibration_pass,
            "pass": bool(predictive_pass and calibration_pass),
        }

    fit = key_math.get("fit")
    if not isinstance(fit, Mapping):
        raise ValueError("NFL_V2J_ADJUDICATION_KEY_FIT_MISSING")
    tolerance = float(fit.get("max_abs_error", -1.0))
    if abs(tolerance - key_tolerance) > 1e-12:
        raise ValueError("NFL_V2J_ADJUDICATION_KEY_TOLERANCE_DRIFT")
    key_pass = fit.get("pass") is True

    historical_predictive_pass = all(
        bool(market_gates[market]["historical_predictive_pass"])
        for market in _MARKETS
    )
    calibration_pass = all(
        bool(market_gates[market]["calibration_pass"])
        for market in _MARKETS
    )
    frozen_gate_pass = bool(historical_predictive_pass and calibration_pass and key_pass)

    return {
        "schema_version": 1,
        "contract": "NFL_V2J_POSTRUN_ADJUDICATION_V1",
        "status": "COMPLETE_ZERO_AUTHORITY",
        "verdict": (
            "V2J_FROZEN_GATES_PASS_ZERO_AUTHORITY"
            if frozen_gate_pass
            else "V2J_FROZEN_GATES_FAIL_ZERO_AUTHORITY"
        ),
        "upstream_run_id": int(upstream_run_id),
        "upstream_head_sha": _sha(upstream_head_sha, length=40, label="UPSTREAM_HEAD_SHA"),
        "adjudicator_git_sha": _sha(adjudicator_git_sha, length=40, label="ADJUDICATOR_GIT_SHA"),
        "first_readout_sha256": _sha(first_readout_sha256, length=64, label="READOUT_SHA256"),
        "key_math_sha256": _sha(key_math_sha256, length=64, label="KEY_MATH_SHA256"),
        "policy_sha256": _sha(policy_sha256, length=64, label="POLICY_SHA256"),
        "frozen_thresholds": {
            "spread_fold_win_rate": thresholds["spread_fold"],
            "total_fold_win_rate": thresholds["total_fold"],
            "spread_calibration_max_bin_deviation": thresholds["spread_calibration"],
            "total_calibration_max_bin_deviation": thresholds["total_calibration"],
            "signed_key_max_abs_error": key_tolerance,
        },
        "market_gates": market_gates,
        "signed_key_gate_pass": key_pass,
        "historical_predictive_pass": historical_predictive_pass,
        "calibration_pass": calibration_pass,
        "frozen_gate_pass": frozen_gate_pass,
        "candidate_rejected_by_frozen_gates": not frozen_gate_pass,
        "v2k_automatically_activated": False,
        "nfl_m2_freeze_authorized": False,
        "model_p_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "production_registry_authority": False,
        "note": "This artifact adjudicates only the preregistered V2J historical/calibration/key gates. It grants no bettor-facing or promotion authority and does not select or activate V2K governance.",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first-readout", type=Path, required=True)
    parser.add_argument("--key-math", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--upstream-run-id", type=int, required=True)
    parser.add_argument("--upstream-head-sha", required=True)
    parser.add_argument("--adjudicator-git-sha", required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    first_readout = json.loads(args.first_readout.read_text(encoding="utf-8"))
    key_math = json.loads(args.key_math.read_text(encoding="utf-8"))
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    result = adjudicate(
        first_readout,
        key_math,
        policy,
        upstream_run_id=args.upstream_run_id,
        upstream_head_sha=args.upstream_head_sha,
        adjudicator_git_sha=args.adjudicator_git_sha,
        first_readout_sha256=_file_sha256(args.first_readout),
        key_math_sha256=_file_sha256(args.key_math),
        policy_sha256=_file_sha256(args.policy),
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": result["verdict"], "frozen_gate_pass": result["frozen_gate_pass"], "promotion_authority": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
