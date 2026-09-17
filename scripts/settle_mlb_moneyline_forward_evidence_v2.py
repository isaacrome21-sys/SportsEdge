#!/usr/bin/env python3
"""Settle pregame-frozen MLB MONEYLINE V2 PAPER bets and score fixed checkpoints.

Legacy reconstructed decisions are never reinterpreted under Promotion Evidence
Policy V2. PAPER passes and BLOCKED rows remain auditable but do not enter the
graded-bet denominator. Missing closes remain in the checkpoint denominator and
are excluded from CLV. Promotion is evaluated only on immutable fixed prefixes
of 50, 100, and 150 graded bets within one evidence unit; this module never
grants deployment, staking, promotion, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from math import exp, isfinite, lgamma, log, log1p, sqrt
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Mapping

from scripts.settle_mlb_moneyline_forward_evidence import fetch_final_settlement
from sportsedge.mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)
from sportsedge.mlb_moneyline_v2_settlement import (
    MLBMoneylineV2SettlementError,
    complete_v2_evidence,
)

SETTLEMENT_RUNNER_VERSION = "mlb_moneyline_forward_settlement_runner_v2"
CHECKPOINT_EVALUATOR_VERSION = "mlb_moneyline_v2_fixed_checkpoint_evaluator_v1"
DEFAULT_PREDICTION_ROOT = "data/mlb_forward_predictions"
DEFAULT_QUOTE_ROOT = "data/mlb_forward_capture"
DEFAULT_DECISION_ROOT = "data/mlb_forward_decisions"
DEFAULT_OUTPUT_ROOT = "data/mlb_forward_evidence"
DEFAULT_RAW_ROOT = "data/mlb_forward_settlement_raw"
DEFAULT_CHECKPOINT_ROOT = "data/mlb_forward_checkpoints"
DEFAULT_REPORT = "artifacts/mlb_moneyline_forward_gate_report_v2.json"
DEFAULT_POLICY = "config/promotion_evidence_policy_v2.json"
FIXED_CHECKPOINTS = (50, 100, 150)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MLBMoneylineV2RunnerError(RuntimeError):
    pass


def _utc(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise MLBMoneylineV2RunnerError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _parse_ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise MLBMoneylineV2RunnerError(f"{field} invalid") from exc
    return _utc(parsed, field)


def _json_files(root: str | Path) -> list[dict[str, Any]]:
    path = Path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for item in sorted(path.rglob("*.json")):
        try:
            row = json.loads(item.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MLBMoneylineV2RunnerError(f"invalid JSON: {item}") from exc
        if not isinstance(row, dict):
            raise MLBMoneylineV2RunnerError(f"JSON object required: {item}")
        rows.append(row)
    return rows


def _load_policy(path: str | Path = DEFAULT_POLICY) -> dict[str, Any]:
    try:
        policy = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBMoneylineV2RunnerError("promotion evidence policy unreadable") from exc
    if not isinstance(policy, dict) or policy.get("policy_id") != "PROMOTION_EVIDENCE_POLICY_V2":
        raise MLBMoneylineV2RunnerError("promotion evidence policy mismatch")
    expected = list(policy.get("checkpoints", {}).get("evaluate_only_at_graded_counts") or ())
    if expected != list(FIXED_CHECKPOINTS):
        raise MLBMoneylineV2RunnerError("fixed checkpoint policy mismatch")
    inference = policy.get("forward_capture", {}).get("clv_inference") or {}
    if (
        inference.get("standard_error") != "CR1_CLUSTER_BY_SLATE_DATE"
        or inference.get("cluster_key") != "slate_date"
        or inference.get("reference_distribution") != "STUDENT_T_G_MINUS_1"
        or int(inference.get("minimum_clusters_for_interval", -1)) != 5
        or inference.get("continuous_peeking_for_promotion") is not False
    ):
        raise MLBMoneylineV2RunnerError("CLV inference policy mismatch")
    return policy


def _canonical_bytes(row: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(row), indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_sha256(row: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(row), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _write_create_only(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise MLBMoneylineV2RunnerError(f"immutable evidence collision: {path}")
        return
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        if path.read_bytes() != payload:
            raise MLBMoneylineV2RunnerError(f"immutable evidence collision: {path}")


def _prediction_index(rows: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("prediction game_pk invalid") from exc
        current = dict(row)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(current):
            raise MLBMoneylineV2RunnerError(f"conflicting prediction for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _decision_index(rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    allowed = {"PAPER_BET_FROZEN", "PAPER_PASS_FROZEN", "BLOCKED_MISSED_DECISION_FREEZE"}
    for row in rows:
        if row.get("status") not in allowed:
            raise MLBMoneylineV2RunnerError("decision status invalid")
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise MLBMoneylineV2RunnerError(str(exc)) from exc
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("decision game_pk invalid") from exc
        current = dict(row)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(current):
            raise MLBMoneylineV2RunnerError(f"conflicting decision for game_pk={game_pk}")
        out[game_pk] = current
    return out


def _completed_index(
    rows: Iterable[Mapping[str, Any]], binding: Mapping[str, Any]
) -> tuple[dict[int, dict[str, Any]], int]:
    out: dict[int, dict[str, Any]] = {}
    legacy = 0
    for row in rows:
        if row.get("status") != "FORWARD_EVIDENCE_COMPLETE_V2":
            legacy += 1
            continue
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError as exc:
            raise MLBMoneylineV2RunnerError(str(exc)) from exc
        try:
            game_pk = int(row.get("game_pk"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("completed V2 game_pk invalid") from exc
        current = dict(row)
        if game_pk in out and _canonical_bytes(out[game_pk]) != _canonical_bytes(current):
            raise MLBMoneylineV2RunnerError(f"conflicting V2 evidence for game_pk={game_pk}")
        out[game_pk] = current
    return out, legacy


def _next_checkpoint(n: int) -> int | None:
    for checkpoint in FIXED_CHECKPOINTS:
        if n < checkpoint:
            return checkpoint
    return None


def _betacf(a: float, b: float, x: float) -> float:
    max_iter = 300
    eps = 3e-14
    fpmin = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < fpmin:
        d = fpmin
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < fpmin:
            d = fpmin
        c = 1.0 + aa / c
        if abs(c) < fpmin:
            c = fpmin
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) <= eps:
            return h
    raise MLBMoneylineV2RunnerError("student-t beta continued fraction did not converge")


def _regularized_beta(x: float, a: float, b: float) -> float:
    if not 0.0 <= x <= 1.0 or a <= 0.0 or b <= 0.0:
        raise MLBMoneylineV2RunnerError("student-t beta arguments invalid")
    if x in (0.0, 1.0):
        return x
    log_bt = (
        lgamma(a + b)
        - lgamma(a)
        - lgamma(b)
        + a * log(x)
        + b * log1p(-x)
    )
    bt = exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def _student_t_cdf(value: float, df: int) -> float:
    if df < 1 or not isfinite(value):
        raise MLBMoneylineV2RunnerError("student-t arguments invalid")
    if value == 0.0:
        return 0.5
    x = df / (df + value * value)
    ib = _regularized_beta(x, df / 2.0, 0.5)
    return 1.0 - 0.5 * ib if value > 0 else 0.5 * ib


def _student_t_quantile(probability: float, df: int) -> float:
    if not 0.0 < probability < 1.0 or df < 1:
        raise MLBMoneylineV2RunnerError("student-t quantile arguments invalid")
    if probability == 0.5:
        return 0.0
    if probability < 0.5:
        return -_student_t_quantile(1.0 - probability, df)
    low, high = 0.0, 1.0
    while _student_t_cdf(high, df) < probability:
        high *= 2.0
        if high > 1e6:
            raise MLBMoneylineV2RunnerError("student-t quantile bracket failed")
    for _ in range(120):
        mid = (low + high) / 2.0
        if _student_t_cdf(mid, df) < probability:
            low = mid
        else:
            high = mid
    return (low + high) / 2.0


def _clv_interval(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    close_rows = [row for row in rows if row.get("close_status") == "AVAILABLE"]
    if not close_rows:
        return {
            "close_row_count": 0,
            "close_cluster_count": 0,
            "mean_clv_probability_points": None,
            "cr1_cluster_se_probability_points": None,
            "student_t_df": None,
            "student_t_critical_975": None,
            "clv_95_ci_lower_probability_points": None,
            "clv_95_ci_upper_probability_points": None,
            "interval_status": "INSUFFICIENT_CLOSE_CLUSTERS",
        }
    values: list[float] = []
    clusters: dict[str, list[float]] = {}
    for row in close_rows:
        try:
            value = float(row.get("clv_probability_points"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError("close row CLV invalid") from exc
        if not isfinite(value):
            raise MLBMoneylineV2RunnerError("close row CLV invalid")
        slate = str(row.get("slate_date") or "")
        if not slate:
            raise MLBMoneylineV2RunnerError("close row slate_date required")
        values.append(value)
        clusters.setdefault(slate, []).append(value)
    mean = sum(values) / len(values)
    g = len(clusters)
    if g < 5:
        return {
            "close_row_count": len(values),
            "close_cluster_count": g,
            "mean_clv_probability_points": mean,
            "cr1_cluster_se_probability_points": None,
            "student_t_df": None,
            "student_t_critical_975": None,
            "clv_95_ci_lower_probability_points": None,
            "clv_95_ci_upper_probability_points": None,
            "interval_status": "INSUFFICIENT_CLOSE_CLUSTERS",
        }
    score_squares = 0.0
    for cluster_values in clusters.values():
        cluster_score = sum(value - mean for value in cluster_values)
        score_squares += cluster_score * cluster_score
    variance = (g / (g - 1.0)) * score_squares / (len(values) ** 2)
    se = sqrt(max(variance, 0.0))
    df = g - 1
    critical = _student_t_quantile(0.975, df)
    return {
        "close_row_count": len(values),
        "close_cluster_count": g,
        "mean_clv_probability_points": mean,
        "cr1_cluster_se_probability_points": se,
        "student_t_df": df,
        "student_t_critical_975": critical,
        "clv_95_ci_lower_probability_points": mean - critical * se,
        "clv_95_ci_upper_probability_points": mean + critical * se,
        "interval_status": "AVAILABLE",
    }


def _evidence_sort_key(row: Mapping[str, Any]) -> tuple[datetime, int]:
    return (
        _parse_ts(row.get("decision_frozen_at_utc"), "decision_frozen_at_utc"),
        int(row.get("game_pk")),
    )


def _unit_rows(rows: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    units: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        artifact = str(row.get("model_artifact_sha256") or "")
        if not _SHA256_RE.fullmatch(artifact):
            raise MLBMoneylineV2RunnerError("completed evidence model artifact SHA256 invalid")
        units.setdefault(artifact, []).append(dict(row))
    for values in units.values():
        values.sort(key=_evidence_sort_key)
    return dict(sorted(units.items()))


def _integrity_findings(rows: list[Mapping[str, Any]], binding: Mapping[str, Any]) -> list[str]:
    findings: list[str] = []
    seen_games: set[int] = set()
    for index, row in enumerate(rows):
        prefix = f"row_{index}"
        try:
            require_record_binding(row, binding)
        except MLBMoneylineForwardLaneError:
            findings.append(f"{prefix}:EVIDENCE_ROW_NOT_BOUND_TO_POLICY_SHA256")
        if row.get("status") != "FORWARD_EVIDENCE_COMPLETE_V2":
            findings.append(f"{prefix}:INVALID_EVIDENCE_STATUS")
        if row.get("graded_bet") is not True or row.get("evidence_counts") is not True:
            findings.append(f"{prefix}:INVALID_GRADED_FLAGS")
        if row.get("state") != "PAPER" or float(row.get("stake_units", -1)) != 0.0:
            findings.append(f"{prefix}:INVALID_PAPER_STATE")
        if row.get("promotion_authority") is not False:
            findings.append(f"{prefix}:AUTHORITY_ESCALATION")
        artifact = str(row.get("model_artifact_sha256") or "")
        if not _SHA256_RE.fullmatch(artifact):
            findings.append(f"{prefix}:MODEL_P_NOT_GENUINE_OR_NOT_BOUND_TO_FROZEN_ARTIFACT")
        try:
            game_pk = int(row.get("game_pk"))
            if game_pk in seen_games:
                findings.append(f"{prefix}:DUPLICATE_OR_MUTATED_EVIDENCE_ROW")
            seen_games.add(game_pk)
        except (TypeError, ValueError):
            findings.append(f"{prefix}:INVALID_GAME_ID")
        try:
            _parse_ts(row.get("decision_frozen_at_utc"), "decision_frozen_at_utc")
        except MLBMoneylineV2RunnerError:
            findings.append(f"{prefix}:DECISION_TIMESTAMP_INVALID")
        for field in ("entry_home_odds", "entry_away_odds"):
            try:
                float(row.get(field))
            except (TypeError, ValueError):
                findings.append(f"{prefix}:WORKING_TWO_SIDED_PREGAME_CAPTURE_MISSING")
                break
        if not str(row.get("decision_provider_event_id") or ""):
            findings.append(f"{prefix}:WORKING_TWO_SIDED_PREGAME_CAPTURE_MISSING")
        close_status = row.get("close_status")
        if close_status not in {"AVAILABLE", "MISSING"}:
            findings.append(f"{prefix}:CLOSE_STATUS_INVALID")
        if close_status == "AVAILABLE":
            if row.get("clv_probability_points") is None:
                findings.append(f"{prefix}:CLOSE_CLV_MISSING")
            for field in ("close_home_odds", "close_away_odds"):
                try:
                    float(row.get(field))
                except (TypeError, ValueError):
                    findings.append(f"{prefix}:WORKING_TWO_SIDED_CLOSE_CAPTURE_MISSING")
                    break
        if row.get("settlement_status") != "FINAL":
            findings.append(f"{prefix}:FINAL_SETTLEMENT_REQUIRED")
        try:
            float(row.get("paper_roi_fraction_per_1u"))
        except (TypeError, ValueError):
            findings.append(f"{prefix}:ROI_INVALID")
    return sorted(set(findings))


def _checkpoint_policy(policy: Mapping[str, Any], checkpoint: int) -> Mapping[str, Any]:
    value = policy.get("checkpoints", {}).get(f"checkpoint_{checkpoint}")
    if not isinstance(value, Mapping):
        raise MLBMoneylineV2RunnerError(f"checkpoint policy missing: {checkpoint}")
    return value


def _evaluate_checkpoint(
    rows: list[Mapping[str, Any]],
    *,
    checkpoint: int,
    binding: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if checkpoint not in FIXED_CHECKPOINTS or len(rows) != checkpoint:
        raise MLBMoneylineV2RunnerError("checkpoint evaluator requires exact fixed prefix")
    artifact_set = {str(row.get("model_artifact_sha256") or "") for row in rows}
    if len(artifact_set) != 1:
        raise MLBMoneylineV2RunnerError("checkpoint evidence unit mixes model artifacts")
    artifact = next(iter(artifact_set))
    if not _SHA256_RE.fullmatch(artifact):
        raise MLBMoneylineV2RunnerError("checkpoint model artifact SHA256 invalid")
    cp = _checkpoint_policy(policy, checkpoint)
    integrity = _integrity_findings(rows, binding)
    distinct_games = len({int(row["game_pk"]) for row in rows})
    slate_clusters = len({str(row.get("slate_date") or "") for row in rows if row.get("slate_date")})
    closes = [row for row in rows if row.get("close_status") == "AVAILABLE"]
    close_coverage = len(closes) / checkpoint
    roi = sum(float(row["paper_roi_fraction_per_1u"]) for row in rows) / checkpoint
    clv = _clv_interval(rows)
    entry_checks = {
        "frozen_lane_definition": bool(binding.get("lane_definition_sha256")),
        "genuine_model_p_from_frozen_artifact": all(
            str(row.get("model_artifact_sha256") or "") == artifact for row in rows
        ),
        "working_two_sided_pregame_capture": all(
            row.get("entry_home_odds") is not None
            and row.get("entry_away_odds") is not None
            and bool(row.get("decision_provider_event_id"))
            for row in rows
        ),
        "working_two_sided_close_capture": bool(closes)
        and all(row.get("close_home_odds") is not None and row.get("close_away_odds") is not None for row in closes),
    }
    min_games = int(cp.get("min_distinct_games", 0))
    min_clusters = int(cp.get("min_slate_clusters", 0))
    min_coverage = float(cp.get("min_close_coverage", 0.0))
    max_roi_loss = float(cp.get("max_roi_loss_fraction", 1.0))
    base_checks = {
        "integrity_clear": not integrity,
        "graded_count_exact": len(rows) == checkpoint,
        "distinct_games": distinct_games >= min_games,
        "slate_clusters": slate_clusters >= min_clusters,
        "close_coverage": close_coverage >= min_coverage,
        "roi_loss_limit": roi >= -max_roi_loss,
    }
    if checkpoint == 50:
        base_checks["mean_clv_nonnegative"] = (
            clv["mean_clv_probability_points"] is not None
            and float(clv["mean_clv_probability_points"]) >= float(cp.get("min_mean_clv_pp", 0.0))
        )
        base_checks["required_before_entry"] = all(entry_checks.values())
    if checkpoint == 150:
        base_checks["clv_interval_available"] = clv["interval_status"] == "AVAILABLE"
        base_checks["clv_ci_lower_positive"] = (
            clv["clv_95_ci_lower_probability_points"] is not None
            and float(clv["clv_95_ci_lower_probability_points"])
            > float(cp.get("clv_ci_lower_pp_must_be_above", 0.0))
        )

    kill_reasons: list[str] = []
    upper = clv.get("clv_95_ci_upper_probability_points")
    if upper is not None and float(upper) < 0.0:
        kill_reasons.append("CLV_95_CI_UPPER_BELOW_ZERO")
    if roi < -0.075:
        kill_reasons.append("ROI_FRACTION_BELOW_MINUS_0_075")
    if close_coverage < 0.90:
        kill_reasons.append("CLOSE_COVERAGE_BELOW_0_90")

    warnings = [
        {
            "warning": "NONCRITICAL_DIAGNOSTIC_MISSING",
            "status": "UNRESOLVED",
            "reason": "Calibration warning clearance/signoff is a separate bound evidence surface; this checkpoint evaluator cannot self-clear it.",
        }
    ]
    warnings_ready = False
    if checkpoint == 50:
        candidate = all(base_checks.values()) and not kill_reasons
        disposition = "PROBATION_CANDIDATE" if candidate else "PAPER_REQUIRED"
    elif checkpoint == 100:
        candidate = all(base_checks.values()) and not kill_reasons
        disposition = "PROBATION_CONTINUE_CANDIDATE" if candidate else "PAPER_REQUIRED"
    else:
        base_checks["warnings_cleared_or_signed_off"] = warnings_ready
        candidate = all(base_checks.values()) and not kill_reasons
        disposition = "OFFICIAL_CANDIDATE" if candidate else "PAPER_REQUIRED"

    return {
        "schema_version": CHECKPOINT_EVALUATOR_VERSION,
        "policy_id": binding["policy_id"],
        "policy_sha256": binding["policy_sha256"],
        "lane_id": binding["lane_id"],
        "lane_definition_sha256": binding["lane_definition_sha256"],
        "market_definition_sha256": binding["market_definition_sha256"],
        "model_artifact_sha256": artifact,
        "checkpoint_graded_count": checkpoint,
        "evaluation_basis": "IMMUTABLE_FIRST_K_GRADED_ROWS_WITHIN_EVIDENCE_UNIT",
        "continuous_peeking_for_promotion": False,
        "distinct_games": distinct_games,
        "slate_clusters": slate_clusters,
        "close_coverage": close_coverage,
        "mean_paper_roi_fraction_per_1u": roi,
        "clv_inference": clv,
        "required_before_entry": entry_checks,
        "checks": base_checks,
        "integrity_findings": integrity,
        "kill_reasons": kill_reasons,
        "warnings": warnings,
        "warnings_ready_for_official": warnings_ready,
        "target_state": cp.get("target_state"),
        "disposition": disposition,
        "evidence_row_sha256": [_canonical_sha256(row) for row in rows],
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
    }


def _checkpoint_snapshots(
    rows: Iterable[Mapping[str, Any]],
    *,
    binding: Mapping[str, Any],
    policy: Mapping[str, Any],
    checkpoint_root: str | Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    evaluations: list[dict[str, Any]] = []
    retained_paths: list[str] = []
    for artifact, unit in _unit_rows(rows).items():
        for checkpoint in FIXED_CHECKPOINTS:
            if len(unit) < checkpoint:
                continue
            evaluation = _evaluate_checkpoint(
                unit[:checkpoint], checkpoint=checkpoint, binding=binding, policy=policy
            )
            path = (
                Path(checkpoint_root)
                / str(binding["lane_id"])
                / artifact
                / str(binding["policy_sha256"])
                / f"checkpoint_{checkpoint:03d}.json"
            )
            payload = _canonical_bytes(evaluation)
            existed = path.exists()
            _write_create_only(path, payload)
            if not existed:
                retained_paths.append(str(path))
            evaluations.append(evaluation)
    return evaluations, retained_paths


def settle_v2(
    *,
    prediction_root: str | Path = DEFAULT_PREDICTION_ROOT,
    quote_root: str | Path = DEFAULT_QUOTE_ROOT,
    decision_root: str | Path = DEFAULT_DECISION_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    raw_root: str | Path = DEFAULT_RAW_ROOT,
    checkpoint_root: str | Path = DEFAULT_CHECKPOINT_ROOT,
    report_path: str | Path = DEFAULT_REPORT,
    policy_path: str | Path = DEFAULT_POLICY,
    now: datetime | None = None,
    settlement_fetcher: Callable[[int], Mapping[str, Any] | None] | None = None,
) -> dict[str, Any]:
    now_utc = _utc(now or datetime.now(timezone.utc), "now")
    binding = load_forward_lane_binding()
    policy = _load_policy(policy_path)
    predictions = _prediction_index(_json_files(prediction_root))
    quotes = _json_files(quote_root)
    decisions = _decision_index(_json_files(decision_root), binding)
    completed, legacy_count = _completed_index(_json_files(output_root), binding)
    fetcher = settlement_fetcher or (lambda game_pk: fetch_final_settlement(game_pk))

    frozen_bets = [row for row in decisions.values() if row.get("status") == "PAPER_BET_FROZEN"]
    paper_passes = [row for row in decisions.values() if row.get("status") == "PAPER_PASS_FROZEN"]
    blocked_decisions = [
        row for row in decisions.values() if row.get("status") == "BLOCKED_MISSED_DECISION_FREEZE"
    ]
    retained: list[str] = []
    pending_start: list[int] = []
    pending_final: list[int] = []

    for decision in sorted(frozen_bets, key=lambda row: int(row["game_pk"])):
        game_pk = int(decision["game_pk"])
        if game_pk in completed:
            continue
        prediction = predictions.get(game_pk)
        if prediction is None:
            raise MLBMoneylineV2RunnerError(
                f"missing frozen prediction for graded decision game_pk={game_pk}"
            )
        start = _parse_ts(decision.get("event_start_ts"), "event_start_ts")
        if now_utc <= start:
            pending_start.append(game_pk)
            continue
        source = fetcher(game_pk)
        if source is None:
            pending_final.append(game_pk)
            continue
        if not isinstance(source, Mapping):
            raise MLBMoneylineV2RunnerError(f"settlement source invalid for {game_pk}")
        settlement = dict(source.get("settlement") or {})
        try:
            pred_away_id = int(prediction.get("away_team_id"))
            pred_home_id = int(prediction.get("home_team_id"))
            settle_away_id = int(settlement.get("away_team_id"))
            settle_home_id = int(settlement.get("home_team_id"))
        except (TypeError, ValueError) as exc:
            raise MLBMoneylineV2RunnerError(
                f"settlement team identity invalid for {game_pk}"
            ) from exc
        if (pred_away_id, pred_home_id) != (settle_away_id, settle_home_id):
            raise MLBMoneylineV2RunnerError(
                f"settlement team identity mismatch for {game_pk}"
            )
        try:
            record = complete_v2_evidence(
                decision=decision,
                prediction=prediction,
                quotes=quotes,
                settlement={
                    "game_pk": game_pk,
                    "status": settlement.get("status"),
                    "away_score": settlement.get("away_score"),
                    "home_score": settlement.get("home_score"),
                },
                binding=binding,
            )
        except MLBMoneylineV2SettlementError as exc:
            raise MLBMoneylineV2RunnerError(
                f"V2 settlement invalid for {game_pk}: {exc}"
            ) from exc
        raw = source.get("raw_bytes")
        if not isinstance(raw, (bytes, bytearray)):
            raise MLBMoneylineV2RunnerError(f"raw settlement bytes required for {game_pk}")
        raw_bytes = bytes(raw)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        if str(source.get("raw_sha256") or "") != raw_sha:
            raise MLBMoneylineV2RunnerError(
                f"settlement raw SHA mismatch for {game_pk}"
            )
        source_uri = str(source.get("source_uri") or "")
        if not source_uri.startswith("https://statsapi.mlb.com/"):
            raise MLBMoneylineV2RunnerError(
                f"settlement source URI invalid for {game_pk}"
            )
        observed_at = str(source.get("observed_at_utc") or "")
        _parse_ts(observed_at, "settlement observed_at_utc")
        record.update(
            {
                "settlement_runner_version": SETTLEMENT_RUNNER_VERSION,
                "settlement_observed_at_utc": observed_at,
                "settlement_source_uri": source_uri,
                "settlement_raw_sha256": raw_sha,
                "settlement_away_team_id": settle_away_id,
                "settlement_home_team_id": settle_home_id,
                "settlement_source_class": "MLB_STATSAPI_SCHEDULE_FINAL",
            }
        )
        day = str(decision.get("slate_date") or start.date().isoformat())
        raw_path = Path(raw_root) / day / f"game_{game_pk}__{raw_sha}.json"
        evidence_path = Path(output_root) / day / f"game_{game_pk}__v2.json"
        _write_create_only(raw_path, raw_bytes)
        _write_create_only(evidence_path, _canonical_bytes(record))
        retained.append(str(evidence_path))
        completed[game_pk] = record

    completed_rows = list(completed.values())
    unit_map = _unit_rows(completed_rows)
    checkpoint_evaluations, checkpoint_paths = _checkpoint_snapshots(
        completed_rows,
        binding=binding,
        policy=policy,
        checkpoint_root=checkpoint_root,
    )
    closes = [row for row in completed_rows if row.get("close_status") == "AVAILABLE"]
    clv_values = [float(row["clv_probability_points"]) for row in closes]
    roi_values = [float(row["paper_roi_fraction_per_1u"]) for row in completed_rows]
    unit_summary = [
        {
            "model_artifact_sha256": artifact,
            "graded_bets": len(rows),
            "next_checkpoint": _next_checkpoint(len(rows)),
            "reached_checkpoints": [
                checkpoint for checkpoint in FIXED_CHECKPOINTS if len(rows) >= checkpoint
            ],
        }
        for artifact, rows in unit_map.items()
    ]
    report = {
        "schema_version": SETTLEMENT_RUNNER_VERSION,
        "generated_at_utc": now_utc.isoformat(),
        "active_policy_id": binding["policy_id"],
        "policy_sha256": binding["policy_sha256"],
        "lane_id": binding["lane_id"],
        "lane_definition_sha256": binding["lane_definition_sha256"],
        "market_definition_sha256": binding["market_definition_sha256"],
        "predictions_seen": len(predictions),
        "quotes_seen": len(quotes),
        "decisions_seen": len(decisions),
        "paper_bets_frozen": len(frozen_bets),
        "paper_passes_frozen": len(paper_passes),
        "blocked_decisions": len(blocked_decisions),
        "completed_v2_graded_bets": len(completed_rows),
        "completed_v2_graded_bets_are_cross_unit_diagnostic_only": True,
        "evidence_units": unit_summary,
        "new_completed_v2_bets": len(retained),
        "retained_paths": retained,
        "legacy_non_v2_completed_rows_ignored": legacy_count,
        "pending_start_game_pks": pending_start,
        "pending_final_game_pks": pending_final,
        "close_rows_available": len(closes),
        "close_coverage": (len(closes) / len(completed_rows)) if completed_rows else 0.0,
        "mean_clv_probability_points": (
            sum(clv_values) / len(clv_values) if clv_values else None
        ),
        "mean_paper_roi_fraction_per_1u": (
            sum(roi_values) / len(roi_values) if roi_values else None
        ),
        "fixed_checkpoints": list(FIXED_CHECKPOINTS),
        "next_checkpoint": (
            _next_checkpoint(len(next(iter(unit_map.values())))) if len(unit_map) == 1 else None
        ),
        "checkpoint_evaluator_status": "ACTIVE_FIXED_PREFIX_50_100_150",
        "checkpoint_evaluator_version": CHECKPOINT_EVALUATOR_VERSION,
        "checkpoint_evaluations": checkpoint_evaluations,
        "new_checkpoint_snapshot_paths": checkpoint_paths,
        "calibration_status": "SEPARATE_BOUND_PIT_CALIBRATION_EVIDENCE_REQUIRED",
        "promotion_authority": False,
        "deployment_change_allowed": False,
        "staking_change_allowed": False,
        "official_change_allowed": False,
        "status": "V2_FORWARD_EVIDENCE_ACCUMULATING",
    }
    target = Path(report_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-root", default=DEFAULT_PREDICTION_ROOT)
    parser.add_argument("--quote-root", default=DEFAULT_QUOTE_ROOT)
    parser.add_argument("--decision-root", default=DEFAULT_DECISION_ROOT)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--checkpoint-root", default=DEFAULT_CHECKPOINT_ROOT)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        report = settle_v2(
            prediction_root=args.prediction_root,
            quote_root=args.quote_root,
            decision_root=args.decision_root,
            output_root=args.output_root,
            raw_root=args.raw_root,
            checkpoint_root=args.checkpoint_root,
            report_path=args.report,
            policy_path=args.policy,
        )
    except (MLBMoneylineV2RunnerError, MLBMoneylineForwardLaneError) as exc:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": str(exc),
                    "promotion_authority": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
